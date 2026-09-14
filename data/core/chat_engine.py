# -*- coding: utf-8 -*-
"""ChatEngine: LLM intent → tools → ответ. Плагины = исполнители, не парсеры фраз."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Dict, List, Optional

from .llm_client import LLMClient
from .plugin_api import AppContext, HookResult

# один поток: tools не блокируют GUI, state не гоняется параллельно
_TOOL_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool")


INTENT_SCHEMA = """Ты классификатор намерений. Ответь ТОЛЬКО одним JSON без markdown:
{"intent":"<имя>","args":{...},"speak":"<короткая фраза пользователю на русском или пусто>"}

intent:
- chat — разговор, знания, объяснить/описать/написать текст, мнение (БЕЗ открытия браузера)
- describe_screen — явно про экран/монитор («что на экране», «посмотри на монитор»)
- web_search — нужно ИСКАТЬ в интернете. args: {"query":"<краткий поисковый запрос 3-8 слов>","mode":"web"|"images"|"video"}
- search_similar — похожее на то что на экране/файл. args: {"kind":"site"|"image"|"generic"}
- download_image — скачать картинку из последней выдачи в чат. args: {"index":1}
- fetch_page — скачать ТЕКСТ страницы из выдачи в чат. args: {"index":1}
- fetch_url — скачать конкретную ссылку (картинка/текст/pdf/json) в чат. args: {"url":"https://..."}
- open_last_search — то же что download_image (картинки) или fetch_page (сайты), НЕ открывать поиск заново

- memory_add / memory_list / memory_forget
- note_add / note_list / note_find
- reminder_add / reminder_list
- pc_open / pc_close / pc_volume / pc_search_files / pc_search_folders
- pc_open_found / pc_close_last / pc_create_text / pc_recycle / pc_empty_recycle
- deep_think — «подробно», «максимально точно», «разбери»

Правила web_search:
- Срабатывает на: найди, поищи, погугли, загугли, в интернете, в гугле, поиск, найди картинки/фото/видео, кто такой (если просят найти), сколько стоит (если просят найти цены).
- В args.query — НЕ копируй фразу пользователя целиком.
  Убери: «найди», «поищи», «пожалуйста», «можешь», «в интернете», «в гугле», «для меня».
  Оставь СУТЬ: ключевые слова, имена, названия, язык запроса как удобно для Google.
  Примеры:
  «найди в интернете как настроить asyncio» → query="asyncio setup tutorial python"
  «поищи картинки рыжих кошек» → query="рыжие кошки", mode="images"
  «погугли курс доллара» → query="курс доллара ЦБ"
- mode=images если: картинк, фото, обои, image, art
- mode=video если: видео, youtube, ютуб, ролик

НЕ web_search:
- «что такое asyncio» / «объясни» / «расскажи» → chat (ответь сам)
- «опиши закат» / «напиши стих» → chat
- «найди файл X» / «найди папку» → pc_search_files / pc_search_folders
- «открой её / скачай / в чат» ПОСЛЕ поиска картинок → download_image
- «текст со страницы / что там написано» после поиска сайтов → fetch_page

Если не уверен — chat.
"""


class ChatEngine:
    _ANIM_RE = re.compile(r"\[ANIM:[a-zA-Z0-9_]+\]", re.I)

    @staticmethod
    def _strip_anim_tags_only(text: str) -> str:
        return ChatEngine._ANIM_RE.sub("", text or "")

    @classmethod
    def _strip_anim_for_chat(cls, text: str) -> str:
        t = cls._strip_anim_tags_only(text)
        return " ".join((t or "").split())

    def __init__(self, app: AppContext, llm: LLMClient | None = None):
        self.app = app
        self.llm = llm or LLMClient.from_config(app.config)
        app.llm = self.llm
        self.history: List[Dict[str, str]] = []
        self.system_prompt = getattr(app.config, "SYSTEM_PROMPT", "") or "Ты полезный ассистент."
        app.state.setdefault("context", {})
        app.state["engine"] = self
        try:
            app.engine = self
        except Exception:
            pass

    def _ctx(self) -> Dict[str, Any]:
        st = self.app.state
        return {
            "last_screen_desc": str(st.get("screen_vision_last_desc") or "")[:500],
            "last_screen_query": str(st.get("screen_vision_search_query") or ""),
            "last_search_query": str(st.get("last_search_query") or ""),
            "last_search_mode": str(st.get("last_search_mode") or ""),
            "last_search_n": len(st.get("last_search_results") or []),
            "pending_similar": bool(st.get("screen_vision_pending_similar")),
            "character": str(
                self.app.get_active_character()
                if hasattr(self.app, "get_active_character")
                else getattr(self.app.config, "ACTIVE_CHARACTER", "")
            ),
            "nsfw": bool(st.get("character_nsfw")),
            "emotion": str(st.get("emotion") or "neutral"),
        }

    def _context_block(self) -> str:
        c = self._ctx()
        lines = ["[CONTEXT]"]
        for k, v in c.items():
            if v not in ("", None, False):
                lines.append(f"{k}: {v}")
        return "\n".join(lines)

    async def _classify(self, text: str) -> Dict[str, Any]:
        low = text.strip().lower()
        # быстрые подтверждения без LLM
        if low in ("да", "давай", "ок", "окей", "yes", "ага", "угу", "ищи", "найди", "хорошо"):
            if self.app.state.get("screen_vision_pending_similar"):
                return {"intent": "search_similar", "args": {"kind": "generic"}, "speak": ""}
        fast = self._fast_after_search(low)
        if fast:
            print(f"intent fast: {fast}", flush=True)
            return fast
        try:
            from .intents import classify as rule_classify
            ruled = rule_classify(text, self._ctx())
        except Exception as e:
            print(f"intent rules failed: {e}", flush=True)
            ruled = None
        if ruled is not None:
            print(f"intent rules: {ruled.get('intent')} args={ruled.get('args')}", flush=True)
            return ruled
        ctx = self._context_block()
        messages = [
            {"role": "system", "content": INTENT_SCHEMA + "\n\n" + ctx},
            {"role": "user", "content": text},
        ]
        try:
            raw = await self.llm.chat_once(
                messages, temperature=0.1, max_tokens=200, model=self.llm.model
            )
        except Exception as e:
            print(f"intent: classify failed: {e}", flush=True)
            return {"intent": "chat", "args": {}, "speak": ""}
        parsed = self._parse_intent(raw)
        print(f"intent llm: {parsed.get('intent')} args={parsed.get('args')}", flush=True)
        return parsed

    def _fast_after_search(self, low: str) -> Optional[Dict[str, Any]]:
        """После поиска не ходить в LLM и не открывать Google заново."""
        has = bool(
            self.app.state.get("last_search_results")
            or self.app.state.get("last_search_query")
        )
        if not has:
            return None
        idx = 1
        m = re.search(r"(?:^|\s)(?:номер\s*)?(\d{1,2})(?:\s|$)", low)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 20:
                idx = n
        mode = str(self.app.state.get("last_search_mode") or "web")
        want_dl = any(
            w in low
            for w in (
                "скач", "сохрани", "в чат", "пришли картин", "скинь",
                "эту картин", "лучш", "выдай картин", "выдай фото",
            )
        )
        want_open = (
            low.startswith("открой")
            or low.startswith("открыть")
            or "открой её" in low
            or "открой ее" in low
            or "открой эту" in low
        )
        want_text = any(
            w in low
            for w in ("текст со", "текст страниц", "что там написано", "выдай текст", "содержимое")
        )
        if "вкладк" in low and "чат" not in low:
            return {"intent": "open_last_search", "args": {"browser_only": True}, "speak": ""}
        if want_text:
            return {"intent": "fetch_page", "args": {"index": idx}, "speak": ""}
        if want_dl or want_open:
            if mode == "images" or "картин" in low or "фото" in low or "скач" in low:
                return {"intent": "download_image", "args": {"index": idx}, "speak": ""}
            return {"intent": "fetch_page", "args": {"index": idx}, "speak": ""}
        return None

    @staticmethod
    def _parse_intent(raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {"intent": "chat", "args": {}, "speak": ""}
        # вытащить JSON
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {"intent": "chat", "args": {}, "speak": ""}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {"intent": "chat", "args": {}, "speak": ""}
        intent = str(data.get("intent") or "chat").strip()
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        speak = str(data.get("speak") or "").strip()
        return {"intent": intent, "args": args, "speak": speak}

    def _run_tool(self, intent: str, args: Dict[str, Any]) -> Optional[str]:
        tools = self.app.tools or {}
        # алиасы intent → tool name
        alias = {
            "describe_screen": "describe_screen",
            "web_search": "web_search",
            "search_similar": "search_similar",
            "open_last_search": "open_last_search",
            "download_image": "download_image",
            "fetch_url": "fetch_url",
            "fetch_page": "fetch_page",
            "save_search_result": "download_image",
            "memory_add": "memory_add",
            "memory_list": "memory_list",
            "memory_forget": "memory_forget",
            "note_add": "note_add",
            "note_list": "note_list",
            "note_find": "note_find",
            "reminder_add": "reminder_add",
            "reminder_list": "reminder_list",
            "pc_open": "pc_open",
            "pc_close": "pc_close",
            "pc_volume": "pc_volume",
            "pc_search_files": "pc_search_files",
            "pc_search_folders": "pc_search_folders",
            "pc_open_found": "pc_open_found",
            "pc_close_last": "pc_close_last",
            "pc_create_text": "pc_create_text",
            "pc_recycle": "pc_recycle",
            "pc_empty_recycle": "pc_empty_recycle",
            "deep_think": "deep_think",
        }
        name = alias.get(intent)
        if not name:
            return None
        fn = tools.get(name)
        if not callable(fn):
            return f"Инструмент «{name}» не зарегистрирован (плагин выключен?)."
        try:
            from .tool_args import filter_tool_args
            safe = filter_tool_args(name, args)
        except Exception:
            safe = {}
        try:
            return fn(self.app, **safe)
        except TypeError:
            # args mismatch — вызвать только с app
            try:
                return fn(self.app)
            except Exception as e:
                return f"Ошибка {name}: {e}"
        except Exception as e:
            return f"Ошибка {name}: {e}"

    async def _run_tool_async(self, intent: str, args: Dict[str, Any]) -> Optional[str]:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_TOOL_POOL, self._run_tool, intent, args)

    def _memory_plugin(self):
        try:
            return (self.app.plugins or {}).get("memory")
        except Exception:
            return None

    def _remember(self, role: str, content: str) -> None:
        mem = self._memory_plugin()
        if mem is None or not hasattr(mem, "record"):
            return
        try:
            mem.record(role, content)
        except Exception as e:
            print(f"memory record: {e}", flush=True)

    def _trim_history(self) -> None:
        n = 16
        mem = self._memory_plugin()
        if mem is not None and hasattr(mem, "_tail_n"):
            try:
                n = int(mem._tail_n(self.app) or 16)
            except Exception:
                n = 16
        if len(self.history) > n:
            self.history = self.history[-n:]

    def _schedule_summary(self) -> None:
        mem = self._memory_plugin()
        if mem is None or not hasattr(mem, "maybe_summarize"):
            return
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(mem.maybe_summarize(self.llm))
        except Exception:
            pass

    async def _refine_search_args(self, user_text: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Вытащить нормальный поисковый запрос из фразы пользователя."""
        args = dict(args or {})
        raw_q = str(args.get("query") or user_text or "").strip()
        mode = str(args.get("mode") or "").lower()
        low = (user_text or "").lower()

        if not mode:
            if any(w in low for w in ("картин", "фото", "обои", "image", "арт", "art ")):
                mode = "images"
            elif any(w in low for w in ("видео", "youtube", "ютуб", "ролик")):
                mode = "video"
            else:
                mode = "web"

        # быстрая чистка без LLM
        q = self._strip_search_fluff(raw_q)
        if len(q) < 3:
            q = self._strip_search_fluff(user_text)

        # если всё ещё похоже на целую разговорную фразу — спросить LLM коротко
        need_llm = (
            len(q.split()) > 10
            or any(w in q.lower() for w in ("можешь", "пожалуйста", "хочу", "давай", "мне нужно"))
            or q.lower() == (user_text or "").lower()
        )
        if need_llm:
            try:
                prompt = (
                    "Преврати фразу пользователя в короткий поисковый запрос для Google (3–8 слов). "
                    "Без кавычек и пояснений. Язык: русский или английский — как лучше для поиска.\n"
                    f"Фраза: {user_text}\nЗапрос:"
                )
                refined = await self.llm.chat_once(
                    [
                        {"role": "system", "content": "Ты извлекало поисковых запросов. Ответь одной строкой."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=40,
                )
                refined = self._strip_search_fluff((refined or "").strip().strip('"').strip("'"))
                if len(refined) >= 2:
                    q = refined
            except Exception as e:
                print(f"intent: refine failed: {e}", flush=True)

        args["query"] = q
        args["mode"] = mode
        return args

    @staticmethod
    def _strip_search_fluff(text: str) -> str:
        import re as _re
        t = (text or "").strip()
        # убрать обёртки
        patterns = [
            r"^\s*(пожалуйста\s*[,:]?\s*)",
            r"^\s*(можешь\s+|можете\s+)",
            r"^\s*(найди|найти|поищи|поискать|погугли|загугли|поиск|поищу)\s+",
            r"^\s*(в\s+интернете|в\s+гугле|в\s+google|в\s+сети|онлайн)\s*",
            r"\s*(в\s+интернете|в\s+гугле|в\s+google|пожалуйста)\s*$",
            r"^\s*(мне\s+|для\s+меня\s+)",
            r"^\s*(картинки|картинку|фото|изображения|видео)\s+(по\s+|про\s+|с\s+)?",
            r"^\s*(как\s+найти)\s+",
        ]
        prev = None
        while prev != t:
            prev = t
            for p in patterns:
                t = _re.sub(p, " ", t, flags=_re.I)
            t = " ".join(t.split())
        return t.strip(" .,!?:;—-")


    async def handle_user(self, text: str) -> AsyncIterator[str]:
        text = (text or "").strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})
        self._remember("user", text)
        self._trim_history()
        import time as _time
        self.app.state["last_user_activity"] = _time.time()
        self.app.state["last_chat_activity"] = _time.time()
        self.app.state["last_user_text"] = text

        # 1) редкие sync-перехваты (голос, подтверждения pc) — если плагин сам handled
        plugs = list(self.app.iter_plugins()) if hasattr(self.app, "iter_plugins") else list(self.app.plugins.values())
        for pl in plugs:
            try:
                hr = pl.on_user_message(text, self.app)
            except Exception as e:
                print(f"[plugin {pl.id}] on_user_message: {e}", flush=True)
                continue
            if isinstance(hr, HookResult) and hr.handled:
                reply = self._strip_anim_for_chat(hr.reply or "")
                self.history.append({"role": "assistant", "content": reply})
                self._remember("assistant", reply)
                self._trim_history()
                self._schedule_summary()
                if reply:
                    yield reply
                return

        # 2) классификация намерения
        classified = await self._classify(text)
        intent = classified.get("intent") or "chat"
        args = classified.get("args") if isinstance(classified.get("args"), dict) else {}
        speak = classified.get("speak") or ""

        # «открой её / скачай» после поиска — НЕ pc_open и НЕ повтор URL поиска
        _low = text.lower()
        has_hits = bool(self.app.state.get("last_search_results") or self.app.state.get("last_search_query"))
        want_media = any(
            w in _low
            for w in ("открой", "открыть", "скачай", "сохрани", "в чат", "пришли", "эту картин", "лучш")
        )
        tgt = str(args.get("target") or "").lower().strip(" .!?,…")
        pronounish = tgt in (
            "", "ее", "её", "его", "их", "это", "эту", "этот", "ту", "то",
            "найденное", "ссылку", "картинку", "ее в другой вкладке",
        )
        if has_hits and want_media and (
            intent in ("pc_open_found", "open_last_search", "chat", "web_search")
            or (intent == "pc_open" and pronounish)
        ):
            mode = str(self.app.state.get("last_search_mode") or "web")
            if mode == "images" or "картин" in _low or "фото" in _low or "скач" in _low:
                intent = "download_image"
            else:
                intent = "fetch_page"
            print(f"intent: remap → {intent} (после поиска, не ПК/не URL выдачи)", flush=True)

        print(f"intent: {intent} args={args}", flush=True)

        # улучшить query для поиска (не сырая фраза пользователя)
        if intent == "web_search":
            args = await self._refine_search_args(text, args)
            print(f"intent: web_search refined args={args}", flush=True)


        if intent == "deep_think":
            self.app.state["llm_max_tokens"] = 4096
            intent = "chat"

        # describe_screen: снимок + обычный LLM с vision-вложением
        if intent == "describe_screen":
            await self._run_tool_async("describe_screen", args)
            self.app.state["screen_vision_attach"] = True
            self.app.state["screen_vision_just_captured"] = True
            intent = "chat"

        if intent != "chat":
            result = await self._run_tool_async(intent, args)
            if result is not None:
                reply = (speak + "\n" + result).strip() if speak else result
                for pl in plugs:
                    try:
                        reply = pl.on_after_llm(reply, self.app) or reply
                    except Exception as e:
                        print(f"[plugin {pl.id}] on_after_llm: {e}", flush=True)
                self.history.append({"role": "assistant", "content": reply})
                self._remember("assistant", reply)
                self._trim_history()
                self._schedule_summary()
                if reply:
                    yield reply
                return

        # 3) обычный чат: карточка персонажа = личность, SYSTEM_PROMPT = служебное
        cid = (
            self.app.get_active_character()
            if hasattr(self.app, "get_active_character")
            else getattr(self.app.config, "ACTIVE_CHARACTER", "default")
        )
        card = ""
        try:
            from character_catalog import read_character_card
            card = (read_character_card(str(cid)) or "").strip()
        except Exception:
            card = ""

        if card:
            system = (
                "Ты не общий ассистент. Ты ИГРАЕШЬ персонажа из карточки. "
                "Речь, характер, желания, границы, обращение к пользователю — только из карточки. "
                "Не ломай образ канцеляритом («чем могу помочь», «как ИИ»). "
                "Длина ответа — как у персонажа, не «всегда коротко» и не «всегда длинно».\n\n"
                f"--- персонаж: {cid} ---\n{card}\n"
            )
            extra_sys = (self.system_prompt or "").strip()
            if extra_sys:
                system += "\n--- служебное (не важнее карточки) ---\n" + extra_sys + "\n"
        else:
            system = self.system_prompt or "Ты живой ассистент."
        system = (system or "") + "\n\n" + self._context_block()
        system += (
            "\nНе предлагай «найти похожее» без смысла. "
            "Если пользователь хочет похожее — он скажет; система сама возьмёт контекст экрана."
        )
        try:
            from core.policy import build_policy_prompt
            system += "\n\n" + build_policy_prompt(self.app)
        except Exception as e:
            print(f"policy: {e}", flush=True)
            if self.app.state.get("character_nsfw") is False:
                system += "\n\n[POLICY SFW] Отказ на 18+."
            elif self.app.state.get("character_nsfw") is True:
                system += "\n\n[POLICY NSFW] 18+ по запросу можно. Запреты из policy.json — всегда."

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        for m in self.history[-16:]:
            messages.append({"role": m["role"], "content": m["content"]})

        for pl in plugs:
            try:
                messages = pl.on_before_llm(messages, self.app) or messages
            except Exception as e:
                print(f"[plugin {pl.id}] on_before_llm: {e}", flush=True)

        extra: Dict[str, Any] = {}
        if self.app.state.get("llm_max_tokens"):
            extra["max_tokens"] = int(self.app.state.pop("llm_max_tokens", 0) or 0) or None
            if extra["max_tokens"] is None:
                extra.pop("max_tokens", None)
        if self.app.state.get("llm_temperature") is not None:
            extra["temperature"] = float(self.app.state["llm_temperature"])

        parts: List[str] = []
        model = getattr(self.app.config, "MODEL_NAME", None) or self.llm.model
        async for chunk in self.llm.chat_stream(messages, model=model, **extra):
            parts.append(chunk)
            yield chunk
        reply = "".join(parts)

        for pl in plugs:
            try:
                reply = pl.on_after_llm(reply, self.app) or reply
            except Exception as e:
                print(f"[plugin {pl.id}] on_after_llm: {e}", flush=True)

        reply = self._strip_anim_for_chat(reply)

        if self.history and self.history[-1]["role"] == "assistant":
            self.history[-1]["content"] = reply
        else:
            self.history.append({"role": "assistant", "content": reply})
        self._remember("assistant", reply)
        self._trim_history()
        self._schedule_summary()
