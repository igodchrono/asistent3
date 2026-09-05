# -*- coding: utf-8 -*-
"""Режим глубокого размышления: длинный точный ответ вместо пары строк."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

_TRIGGER = re.compile(
    r"(?i)("
    r"подробн|"
    r"развёрнут|"
    r"развернут|"
    r"максимально\s+точн|"
    r"максимально\s+подроб|"
    r"глубоко|"
    r"по\s+шагам|"
    r"step\s*by\s*step|"
    r"explain\s+in\s+detail|"
    r"in\s+detail|"
    r"long\s+answer|"
    r"разложи|"
    r"распиши|"
    r"объясни\s+как|"
    r"почему\s+именно|"
    r"с\s+примерами"
    r")"
)

_BLOCK = """
[режим глубокого размышления]
Пользователь просит НЕ короткий ответ.
Нужно:
- сначала кратко зафиксировать задачу;
- разложить по пунктам / шагам;
- дать точные формулировки, исключения и ограничения;
- если уместно — примеры;
- в конце — сжатый итог.
Пиши развёрнуто. Не обрывай мысль на двух предложениях.
Минимум несколько абзацев, пока тема не закрыта.
"""


class PluginImpl(Plugin):
    id = "deep_think"
    name = "Глубокое размышление"
    version = "1.1.0"
    description = "Длинный точный ответ, когда просят подробно / максимально точно"
    # own = отдельная вкладка в настройках (как Голос / Эмоции)
    settings_tab = "own"
    settings_tab_title = "Глубокое размышление"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("always_on", "Всегда длинные ответы", "bool", False),
        SettingField(
            "max_tokens",
            "Лимит токенов в этом режиме",
            "int",
            4096,
            min_value=512,
            max_value=16000,
        ),
        SettingField(
            "temperature",
            "Температура в этом режиме",
            "float",
            0.35,
            min_value=0.0,
            max_value=1.2,
        ),
        SettingField(
            "set_thinking_avatar",
            "Ставить аватару «thinking» в этом режиме",
            "bool",
            True,
        ),
        SettingField(
            "extra_triggers",
            "Доп. триггеры (через |)",
            "str",
            "разбери|проанализируй|сравни|аргументируй",
        ),
    ]

    def __init__(self) -> None:
        self.app: Optional[AppContext] = None
        self._active = False

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["deep_think_plugin"] = self
        print("🧠 deep_think: loaded", flush=True)

    def _triggers_match(self, text: str, app: AppContext) -> bool:
        if _TRIGGER.search(text or ""):
            return True
        extra = str(app.get_plugin_setting(self.id, "extra_triggers", "") or "")
        for part in extra.split("|"):
            part = part.strip().lower()
            if part and part in (text or "").lower():
                return True
        return False

    def on_user_message(self, text: str, app: AppContext) -> None:
        self.app = app
        if not app.get_plugin_setting(self.id, "enabled", True):
            self._active = False
            app.state["deep_think"] = False
            return None
        always = bool(app.get_plugin_setting(self.id, "always_on", False))
        self._active = always or self._triggers_match(text or "", app)
        app.state["deep_think"] = self._active
        if self._active:
            app.state["llm_max_tokens"] = int(
                app.get_plugin_setting(self.id, "max_tokens", 4096) or 4096
            )
            app.state["llm_temperature"] = float(
                app.get_plugin_setting(self.id, "temperature", 0.35) or 0.35
            )
            print("🧠 deep_think: ON", flush=True)
            if app.get_plugin_setting(self.id, "set_thinking_avatar", True):
                emo = app.plugins.get("emotion") or app.state.get("emotion_plugin")
                if emo is not None and hasattr(emo, "set_context"):
                    try:
                        emo.set_context(app, "thinking", "deep_think")
                    except Exception as e:
                        print(f"deep_think emotion: {e}", flush=True)
        else:
            app.state.pop("llm_max_tokens", None)
            app.state.pop("llm_temperature", None)
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not messages:
            return messages
        if not app.state.get("deep_think") and not self._active:
            return messages
        extra = _BLOCK.strip()
        if messages[0].get("role") == "system":
            cur = messages[0].get("content") or ""
            if "[режим глубокого размышления]" not in cur:
                messages[0]["content"] = cur + "\n\n" + extra
        else:
            messages.insert(0, {"role": "system", "content": extra})
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        app.state["deep_think"] = False
        self._active = False
        return reply


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
