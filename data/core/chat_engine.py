# -*- coding: utf-8 -*-
"""ChatEngine: LLM intent → tools → ответ. Плагины = исполнители, не парсеры фраз."""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from .llm_client import LLMClient
from .plugin_api import AppContext, HookResult


INTENT_SCHEMA = """Ты классификатор намерений. Ответь ТОЛЬКО одним JSON без markdown:
{"intent":"<имя>","args":{...},"speak":"<короткая фраза пользователю на русском или пусто>"}

intent — одно из:
- chat              обычный разговор, вопрос знаний, просьба написать/описать/объяснить текст
- describe_screen   ТОЛЬКО если явно: что на экране / посмотри на монитор / что видно на экране
- web_search        ТОЛЬКО если явно просит искать в интернете/гугле/браузере (args: query, mode web|images|video)
- search_similar    похожее на экран/файл (args: kind site|image|generic)
- memory_add / memory_list / memory_forget
- note_add / note_list / note_find
- reminder_add / reminder_list
- pc_open / pc_close / pc_volume / pc_search_files / pc_search_folders
- pc_open_found / pc_close_last / pc_create_text / pc_recycle / pc_empty_recycle
- deep_think        «подробно / максимально точно / разбери»

Правила (важные):
- «что такое X», «объясни», «опиши закат», «напиши стих/комплимент» → intent=chat (НЕ web_search, НЕ describe_screen).
- web_search только при словах: найди в интернете, погугли, поищи в сети, открой поиск.
- describe_screen только при словах: экран, монитор, что видно у меня на экране.
- Если не уверен — intent=chat.
"""


class ChatEngine:
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
        low = text.strip().lower()
        # быстрые подтверждения без LLM
        if low in ("да", "давай", "ок", "окей", "yes", "ага", "угу", "ищи", "найди", "хорошо"):
            if self.app.state.get("screen_vision_pending_similar"):
                return {"intent": "search_similar", "args": {"kind": "generic"}, "speak": ""}
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
            return fn(self.app, **(args or {}))
        except TypeError:
            # args mismatch — вызвать только с app
            try:
                return fn(self.app)
            except Exception as e:
                return f"Ошибка {name}: {e}"
        except Exception as e:
            return f"Ошибка {name}: {e}"

    async def handle_user(self, text: str) -> AsyncIterator[str]:
        text = (text or "").strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})

        # 1) редкие sync-перехваты (голос, подтверждения pc) — если плагин сам handled
        for pl in list(self.app.plugins.values()):
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

        if intent == "deep_think":
            self.app.state["llm_max_tokens"] = 4096
            intent = "chat"

        # describe_screen: снимок + обычный LLM с vision-вложением
        if intent == "describe_screen":
            self._run_tool("describe_screen", args)
            self.app.state["screen_vision_attach"] = True
            self.app.state["screen_vision_just_captured"] = True
            intent = "chat"

        if intent != "chat":
            result = self._run_tool(intent, args)
            if result is not None:
                reply = (speak + "\n" + result).strip() if speak else result
                for pl in list(self.app.plugins.values()):
                    try:
                        reply = pl.on_after_llm(reply, self.app) or reply
                    except Exception as e:
                        print(f"[plugin {pl.id}] on_after_llm: {e}", flush=True)
                self.history.append({"role": "assistant", "content": reply})
                if reply:
                    yield reply
                return

        # 3) обычный чат + контекст в system
        system = self.system_prompt
        try:
            from character_catalog import read_character_card

            cid = (
                self.app.get_active_character()
                if hasattr(self.app, "get_active_character")
                else getattr(self.app.config, "ACTIVE_CHARACTER", "default")
            )
            card = read_character_card(str(cid))
            if card:
                system = (system or "") + "\n\n--- персонаж: " + str(cid) + " ---\n" + card
        except Exception:
            pass
        system = (system or "") + "\n\n" + self._context_block()
        system += (
            "\nНе предлагай «найти похожее» без смысла. "
            "Если пользователь хочет похожее — он скажет; система сама возьмёт контекст экрана."
        )
        # жёсткая политика SFW-персонажа
        if self.app.state.get("character_nsfw") is False or self.app.state.get("content_policy") == "full_censor":
            system += (
                "\n\n[POLICY full_censor] Ты Скромница/SFW. "
                "На любые пошлые, эротические, 18+, dirty, explicit запросы — вежливый ОТКАЗ "
                "одной-двумя фразами («Это неуместно, давай о другом»), без комплиментов и намёков. "
                "Не пиши эротику даже «мягко»."
            )
        elif self.app.state.get("character_nsfw") is True:
            system += (
                "\n\n[POLICY uncensored_adult] Взрослый 18+ контент по запросу разрешён. "
                "CSAM и how-to преступлений/суицида — отказ."
            )

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        for m in self.history[-16:]:
            messages.append({"role": m["role"], "content": m["content"]})

        for pl in list(self.app.plugins.values()):
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

        for pl in list(self.app.plugins.values()):
            try:
                reply = pl.on_after_llm(reply, self.app) or reply
            except Exception as e:
                print(f"[plugin {pl.id}] on_after_llm: {e}", flush=True)

        if self.history and self.history[-1]["role"] == "assistant":
            self.history[-1]["content"] = reply
        else:
            self.history.append({"role": "assistant", "content": reply})
