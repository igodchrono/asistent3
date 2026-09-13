# -*- coding: utf-8 -*-
"""ChatEngine: LLM intent → tools → ответ. Плагины = исполнители, не парсеры фраз."""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from .llm_client import LLMClient
from .plugin_api import AppContext, HookResult
from .intents import classify as fast_classify, strip_search_fluff
from .intents import classify as fast_classify, strip_search_fluff


INTENT_SCHEMA = """Ты классификатор намерений. Ответь ТОЛЬКО одним JSON без markdown:
{"intent":"<имя>","args":{...},"speak":"<короткая фраза пользователю на русском или пусто>"}

intent:
- chat — разговор, знания, код, мнение (БЕЗ браузера)
- describe_screen — СМОТРЕТЬ на монитор и описать/выбрать то что УЖЕ открыто
  («что на экране», «посмотри на них», «выбери самую», «какая лучше», «посмотри на картинки»)
- web_search — НОВЫЙ поиск в интернете. args: {"query":"<3-8 слов>","mode":"web"|"images"|"video"}
- search_similar — НАЙТИ ЕЩЁ в интернете похожее («найди похожие», «такие же но лисички»).
  НЕ для «посмотри и выбери» — это describe_screen.
- memory_add / memory_list / memory_forget
- note_add / note_list / note_find
- reminder_add / reminder_list
- pc_open / pc_close / pc_volume / pc_search_files / pc_search_folders
- pc_open_found / pc_close_last / pc_create_text / pc_recycle / pc_empty_recycle
- deep_think — «подробно», «максимально точно»

Правила web_search:
- query — НЕ копируй фразу. Убери «так», «найди», «картинку», «пожалуйста».
  «так найди картинку аниме девочки акулы» → query="аниме девочка акула", mode="images"
- mode=images: картинк/фото/обои; mode=video: видео/ютуб

НЕ web_search / НЕ search_similar:
- «посмотри на них и выбери» после уже открытого поиска → describe_screen
- «что такое» / «объясни» / «напиши код» / «кусок кода» → chat
- «найди картинки на диске E» / «найди файл» → pc_search_files, не браузер
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

    def _ctx(self) -> Dict[str, Any]:
        st = self.app.state
        return {
            "last_screen_desc": str(st.get("screen_vision_last_desc") or "")[:500],
            "last_screen_query": str(st.get("screen_vision_search_query") or ""),
            "last_file": str(st.get("pc_last_opened") or st.get("pc_last_found") or ""),
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
        st = self.app.state
        fast = fast_classify(text, {
            "last_search_query": st.get("last_search_query"),
            "pending_similar": st.get("screen_vision_pending_similar"),
            "imggen_stage": st.get("imggen_stage"),
        })
        if fast:
            print(f"intent fast: {fast}", flush=True)
            return fast
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
        return self._parse_intent(raw)

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
            "generate_image": "generate_image",
            "memory_add": "memory_add",
            "memory_list": "memory_list",
            "memory_forget": "memory_forget",
            "note_add": "note_add",
            "note_list": "note_list",
            "note_find": "note_find",
            "note_delete": "note_delete",
            "reminder_add": "reminder_add",
            "reminder_list": "reminder_list",
            "reminder_delete": "reminder_delete",
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
            return fn(self.app, **(args or {}))
        except TypeError:
            # args mismatch — вызвать только с app
            try:
                return fn(self.app)
            except Exception as e:
                return f"Ошибка {name}: {e}"
        except Exception as e:
            return f"Ошибка {name}: {e}"

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
        return strip_search_fluff(text)

    def _is_pick_from_results(self, low: str) -> bool:
        if self._is_new_similar_search(low):
            return False
        look = any(w in low for w in (
            "посмотри", "глянь", "посмотр", "на них", "на эти", "на картин",
            "на выдач", "на экран", "на монитор", "на результат",
        ))
        pick = any(w in low for w in (
            "выбери", "выбрать", "самую", "самого", "лучш", "симпатичн",
            "какая лучше", "какой нравит", "какая нравит", "похож",
        ))
        if look and pick:
            return True
        if self.app.state.get("last_search_query") and (look or pick):
            return True
        return False

    @staticmethod
    def _is_new_similar_search(low: str) -> bool:
        return any(w in (low or "") for w in (
            "найди похож", "поищи похож", "найди такие", "поищи такие",
            "такие же но", "такие же, но", "ещё такие", "еще такие",
        ))

    @staticmethod
    def _monitor_hint(text: str) -> Optional[int]:
        low = (text or "").lower()
        if not any(w in low for w in ("монитор", "экран", "дисплей")):
            return None
        if any(w in low for w in ("средн", "второй")):
            return 2
        if any(w in low for w in ("прав", "третий")):
            return 3
        if any(w in low for w in ("лев", "первый", "основн")):
            return 1
        return None

    @staticmethod
    def _strip_images_from_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                texts = []
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(str(part.get("text") or ""))
                nm = dict(m)
                nm["content"] = "\n".join(texts) or str(c)
                out.append(nm)
            else:
                out.append(m)
        return out

    async def handle_user(self, text: str) -> AsyncIterator[str]:
        text = (text or "").strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})
        import time as _time
        self.app.state["last_user_activity"] = _time.time()
        self.app.state["last_chat_activity"] = _time.time()
        self.app.state["last_user_text"] = text

        # 1) редкие sync-перехваты (голос, подтверждения pc) — если плагин сам handled
        for pl in list(self.app.iter_plugins()):
            try:
                hr = pl.on_user_message(text, self.app)
            except Exception as e:
                print(f"[plugin {pl.id}] on_user_message: {e}", flush=True)
                continue
            if isinstance(hr, HookResult) and hr.handled:
                reply = hr.reply or ""
                self.history.append({"role": "assistant", "content": reply})
                if reply:
                    yield reply
                return

        # 2) классификация намерения
        classified = await self._classify(text)
        intent = classified.get("intent") or "chat"
        args = classified.get("args") or {}
        speak = classified.get("speak") or ""
        print(f"intent: {intent} args={args}", flush=True)

        low = (text or "").lower()
        # после веб-поиска «открой» = картинка/выдача, не файл на диске
        if intent in ("pc_open_found", "pc_open") and self.app.state.get("last_search_query"):
            if not any(w in low for w in ("файл", "папк", "диск", "блокнот", "калькулятор", "проводник")):
                print("intent: remap → open_last_search (после поиска, не ПК)", flush=True)
                intent = "open_last_search"
                args = {"text": text}

        # улучшить query для поиска (не сырая фраза пользователя)
        if intent == "web_search":
            args = await self._refine_search_args(text, args)
            print(f"intent: web_search refined args={args}", flush=True)


        if intent == "deep_think":
            self.app.state["llm_max_tokens"] = 4096
            intent = "chat"

        if intent == "search_similar" and self._is_pick_from_results(text.lower()):
            intent = "describe_screen"
            args = {}

        if intent == "describe_screen":
            hint = self._monitor_hint(text)
            if hint:
                self.app.state["screen_monitor_override"] = hint
            elif self.app.state.get("last_search_query") and self.app.state.get("screen_monitor_override") is None:
                # выдача поиска часто на другом мониторе — снимем то окно / все экраны
                self.app.state["screen_capture_search"] = True
            self._run_tool("describe_screen", args)
            self.app.state["screen_vision_attach"] = True
            self.app.state["screen_vision_just_captured"] = True
            last_q = str(self.app.state.get("last_search_query") or "")
            self.app.state["last_tool_note"] = (
                "Сделан снимок монитора. Посмотри ПРИЛОЖЕННУЮ картинку. "
                "Если это сетка поиска — выбери ОДИН кадр: где он (верх/середина/низ, слева/центр/справа), "
                "что на нём и почему. НЕ открывай новый поиск. НЕ пиши SEARCH_OK. "
                + (f"Недавний запрос был: «{last_q}». " if last_q else "")
                + "В конце строка: PICK: <краткое описание выбранного>."
            )
            intent = "chat"

        if intent == "web_search":
            result = self._run_tool("web_search", args)
            q = str(args.get("query") or self.app.state.get("last_search_query") or "")
            mode = str(args.get("mode") or self.app.state.get("last_search_mode") or "web")
            print(f"web_search tool: {result}", flush=True)
            self.app.state["last_tool_note"] = (
                f"Открыла поиск ({mode}): «{q}». Скажи это в образе персонажа. "
                "Не пиши SEARCH_OK и не повторяй служебные теги. "
                "Предложи глянуть вкладку и сказать «посмотри и выбери»."
            )
            intent = "chat"

        if intent == "search_similar":
            result = self._run_tool("search_similar", args)
            q = str(self.app.state.get("last_search_query") or args.get("query") or "")
            print(f"search_similar tool: {result}", flush=True)
            self.app.state["last_tool_note"] = (
                f"Открыла похожий поиск: «{q}». Скажи в образе. Не пиши SEARCH_OK. "
                "Предложи выбрать кадр с экрана."
            )
            intent = "chat"

        if intent == "open_last_search":
            result = self._run_tool("open_last_search", {"text": text, **(args or {})})
            print(f"open_last_search tool: {result}", flush=True)
            self.app.state["last_tool_note"] = (
                f"Открыла выбранное из поиска. Скажи в образе, что открыла. Не пиши SEARCH_OK. {result or ''}"
            )
            intent = "chat"

        if intent != "chat":
            result = self._run_tool(intent, args)
            if result is not None:
                reply = (speak + "\n" + result).strip() if speak else result
                for pl in list(self.app.iter_plugins()):
                    try:
                        reply = pl.on_after_llm(reply, self.app) or reply
                    except Exception as e:
                        print(f"[plugin {pl.id}] on_after_llm: {e}", flush=True)
                self.history.append({"role": "assistant", "content": reply})
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
        note = str(self.app.state.pop("last_tool_note", "") or "").strip()
        if note:
            system += "\n\n[СЕЙЧАС] " + note
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

        for pl in list(self.app.iter_plugins()):
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
        has_img = any(isinstance(m.get("content"), list) for m in messages)
        reply = ""
        if has_img:
            try:
                reply = await self.llm.chat_once(messages, model=model, **extra)
            except Exception as e:
                print(f"llm vision: {e}", flush=True)
                reply = ""
            if not (reply or "").strip() or "error" in (reply or "")[:200].lower():
                print("llm: retry without image (модель без vision)", flush=True)
                messages = self._strip_images_from_messages(messages)
                if messages and messages[0].get("role") == "system":
                    messages[0]["content"] = str(messages[0].get("content") or "") + (
                        "\n[Модель без зрения: снимок не прочитан. Опиши сетку по заголовку окна "
                        f"«{self.app.state.get('screen_react_title') or ''}» и запросу "
                        f"«{self.app.state.get('last_search_query') or ''}». Не открывай новый поиск.]"
                    )
                has_img = False
                reply = ""
            else:
                yield reply
        if not has_img:
            async for chunk in self.llm.chat_stream(messages, model=model, **extra):
                parts.append(chunk)
                yield chunk
            reply = "".join(parts)

        for pl in list(self.app.iter_plugins()):
            try:
                reply = pl.on_after_llm(reply, self.app) or reply
            except Exception as e:
                print(f"[plugin {pl.id}] on_after_llm: {e}", flush=True)

        reply = self._strip_anim_for_chat(reply)

        if self.history and self.history[-1]["role"] == "assistant":
            self.history[-1]["content"] = reply
        else:
            self.history.append({"role": "assistant", "content": reply})
