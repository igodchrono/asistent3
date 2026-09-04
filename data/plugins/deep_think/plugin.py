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
    version = "1.0.0"
    description = "Длинный точный ответ, когда просят подробно / максимально точно"
    settings_tab = "plugins"
    settings_tab_title = "Глубокое размышление"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("always_on", "Всегда длинные ответы", "bool", False),
        SettingField("max_tokens", "Лимит токенов в этом режиме", "int", 4096, min_value=512, max_value=16000),
        SettingField("temperature", "Температура в этом режиме", "float", 0.35, min_value=0.0, max_value=1.2),
    ]

    def __init__(self) -> None:
        self.app: Optional[AppContext] = None
        self._active = False

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["deep_think_plugin"] = self
        print("🧠 deep_think: loaded", flush=True)

    def on_user_message(self, text: str, app: AppContext) -> None:
        self.app = app
        if not app.get_plugin_setting(self.id, "enabled", True):
            self._active = False
            app.state["deep_think"] = False
            return None
        always = bool(app.get_plugin_setting(self.id, "always_on", False))
        self._active = always or bool(_TRIGGER.search(text or ""))
        app.state["deep_think"] = self._active
        if self._active:
            app.state["llm_max_tokens"] = int(app.get_plugin_setting(self.id, "max_tokens", 4096) or 4096)
            app.state["llm_temperature"] = float(app.get_plugin_setting(self.id, "temperature", 0.35) or 0.35)
            print("🧠 deep_think: ON", flush=True)
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
