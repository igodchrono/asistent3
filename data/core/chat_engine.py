# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, AsyncIterator, Dict, List
from .llm_client import LLMClient
from .plugin_api import AppContext, HookResult

class ChatEngine:
    def __init__(self, app: AppContext, llm: LLMClient | None = None):
        self.app = app
        self.llm = llm or LLMClient.from_config(app.config)
        app.llm = self.llm
        self.history: List[Dict[str, str]] = []
        self.system_prompt = getattr(app.config, "SYSTEM_PROMPT", "") or "Ты полезный ассистент."

    async def handle_user(self, text: str) -> AsyncIterator[str]:
        text = (text or "").strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})

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

        system = self.system_prompt
        # карточка персонажа (ядро); плагин persona может заменить в on_before_llm
        try:
            from character_catalog import read_character_card
            cid = self.app.get_active_character() if hasattr(self.app, "get_active_character") else getattr(self.app.config, "ACTIVE_CHARACTER", "default")
            card = read_character_card(str(cid))
            if card:
                system = (system or "") + "\n\n--- персонаж: " + str(cid) + " ---\n" + card
        except Exception:
            pass
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        for m in self.history[-16:]:
            messages.append({"role": m["role"], "content": m["content"]})

        for pl in list(self.app.plugins.values()):
            try:
                messages = pl.on_before_llm(messages, self.app) or messages
            except Exception as e:
                print(f"[plugin {pl.id}] on_before_llm: {e}", flush=True)

        parts: List[str] = []
        model = getattr(self.app.config, "MODEL_NAME", None) or self.llm.model
        async for chunk in self.llm.chat_stream(messages, model=model):
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
