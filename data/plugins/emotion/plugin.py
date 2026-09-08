# -*- coding: utf-8 -*-
"""Эмоции: mood в prompt + [ANIM:] из ответа. Без regex-навыков."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from core.plugin_api import AppContext, Plugin, SettingField

class PluginImpl(Plugin):
    id = "emotion"
    name = "Эмоции"
    version = "4.0.0"
    settings_schema = [SettingField("enabled", "Включить", "bool", True)]

    def on_load(self, app: AppContext) -> None:
        app.state.setdefault("emotion", "neutral")
        app.state.setdefault("emotion_animation", "idle")
        print("🧠 emotion 4.0: mood + [ANIM:] (intent-era)", flush=True)

    def set_context(self, app: AppContext, emotion: str, source: str = "") -> None:
        app.state["emotion"] = emotion
        app.state["emotion_animation"] = emotion
        app.state["emotion_source"] = source

    def on_user_message(self, text, app):
        low = (text or "").lower()
        mapping = [
            (("люб", "love"), "love"),
            (("груст", "печал"), "sad"),
            (("бес", "зл", "раздраж"), "angry"),
            (("ура", "супер", "класс"), "happy"),
            (("смущ", "стесня"), "shy"),
        ]
        for keys, emo in mapping:
            if any(k in low for k in keys):
                self.set_context(app, emo, "user_text")
                break
        return None  # pass-through to LLM/intent

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        mood = str(app.state.get("emotion") or "neutral")
        anim = str(app.state.get("emotion_animation") or mood)
        block = (
            f"\n\n[ЭМОЦИЯ] сейчас {mood}, анимация {anim}. "
            f"В конце ответа можно [ANIM:имя_спрайта] из доступных персонажу.\n"
        )
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        import re
        text = reply or ""
        m = re.search(r"\[ANIM:([^\]]+)\]", text, re.I)
        if m:
            anim = m.group(1).strip()
            app.state["emotion_animation"] = anim
            app.state["emotion"] = anim.split("_")[0]
            print(f"emotion LLM [ANIM:] → {anim}", flush=True)
            # avatar plugin may listen
            av = app.plugins.get("avatar")
            if av and hasattr(av, "set_animation"):
                try:
                    av.set_animation(anim)
                except Exception:
                    pass
        return reply

def register():
    return PluginImpl()
