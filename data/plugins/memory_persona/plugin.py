# -*- coding: utf-8 -*-
"""Долговременная память персонажа через PersistentMemory + авто-факты из чата."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

_FACT_RE = re.compile(
    r"(?i)("
    r"меня\s+зовут\s+(\w+)|"
    r"я\s+живу\s+в\s+([^.!?,\n]{2,40})|"
    r"мне\s+(\d{1,3})\s+лет|"
    r"я\s+работаю\s+([^.!?,\n]{2,40})|"
    r"запомни[:\s]+(.+)|"
    r"remember[:\s]+(.+)"
    r")"
)


class PluginImpl(Plugin):
    id = "memory_persona"
    name = "Долговременная память"
    version = "2.0.0"
    description = "PersistentMemory: факты о пользователе в промпт после рестарта"
    settings_tab = "own"
    settings_tab_title = "Память (долгосрочная)"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("auto_extract", "Авто-факты из сообщений", "bool", True),
        SettingField("inject_prompt", "Вставлять память в промпт", "bool", True),
        SettingField("max_items", "Макс. фактов в промпте", "int", 8, min_value=1, max_value=30),
        SettingField("default_pinned", "Закреплять новые факты", "bool", True),
    ]

    def __init__(self):
        self.app: Optional[AppContext] = None
        self.pm = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["memory_persona_plugin"] = self
        self._open_pm(app)
        if self.pm is not None:
            print(f"🧠 memory_persona: PersistentMemory → {self.pm.db_path}", flush=True)
        else:
            print("memory_persona: PersistentMemory недоступен", flush=True)

    def on_shutdown(self, app: AppContext) -> None:
        if self.pm is not None:
            try:
                self.pm.close()
            except Exception:
                pass
            self.pm = None

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self.app = app
        if self.pm is not None:
            try:
                self.pm.close()
            except Exception:
                pass
        self.pm = None
        self._open_pm(app)

    def on_user_message(self, text: str, app: AppContext):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        if app.get_plugin_setting(self.id, "auto_extract", True):
            self._extract_facts(app, text or "")
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not app.get_plugin_setting(self.id, "inject_prompt", True):
            return messages
        if self.pm is None:
            self._open_pm(app)
        if self.pm is None or not messages:
            return messages
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                query = m["content"]
                break
        scope = self._scope(app)
        limit = int(app.get_plugin_setting(self.id, "max_items", 8) or 8)
        try:
            block = self.pm.get_context_for_prompt(query=query, scope=scope, limit=limit)
        except Exception as e:
            print(f"memory_persona prompt: {e}", flush=True)
            block = ""
        if block and messages[0].get("role") == "system":
            cur = str(messages[0].get("content") or "")
            if "ДОЛГОВРЕМЕННАЯ ПАМЯТЬ" not in cur:
                messages[0]["content"] = cur + "\n" + block
        return messages

    def remember(self, app: AppContext, key: str, value: str, category: str = "fact") -> None:
        if self.pm is None:
            self._open_pm(app)
        if self.pm is None:
            return
        pinned = bool(app.get_plugin_setting(self.id, "default_pinned", True))
        self.pm.add_memory(
            scope=self._scope(app),
            category=category,
            key=key,
            value=value,
            confidence=1.0,
            importance=0.9,
            pinned=pinned,
        )

    def _extract_facts(self, app: AppContext, text: str) -> None:
        if not text or self.pm is None:
            if self.pm is None:
                self._open_pm(app)
            if self.pm is None:
                return
        low = text.strip()
        # запомни: ...
        m = re.search(r"(?i)запомни[:\s]+(.+)", low)
        if m:
            val = m.group(1).strip()[:200]
            self.remember(app, "note", val, "note")
            return
        m = re.search(r"(?i)меня\s+зовут\s+(\w+)", low)
        if m:
            self.remember(app, "name", m.group(1), "profile")
        m = re.search(r"(?i)мне\s+(\d{1,3})\s+лет", low)
        if m:
            self.remember(app, "age", m.group(1), "profile")
        m = re.search(r"(?i)я\s+живу\s+в\s+([^.!?,\n]{2,40})", low)
        if m:
            self.remember(app, "city", m.group(1).strip(), "profile")
        m = re.search(r"(?i)я\s+работаю\s+([^.!?,\n]{2,40})", low)
        if m:
            self.remember(app, "job", m.group(1).strip(), "profile")

    def _open_pm(self, app: AppContext) -> None:
        try:
            from persistent_memory import PersistentMemory

            base = Path(getattr(app.config, "DATA_DIR", Path(".")))
            path = base / "persistent_memory.db"
            # также персонаж-scoped файл
            try:
                cdir = app.get_character_dir()
                path = cdir / "memory" / "persistent_memory.db"
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            self.pm = PersistentMemory(str(path))
            app.state["persistent_memory"] = self.pm
        except Exception as e:
            print(f"memory_persona: no PersistentMemory ({e})", flush=True)
            self.pm = None

    @staticmethod
    def _scope(app: AppContext) -> str:
        try:
            return f"char:{app.get_active_character()}"
        except Exception:
            return "global"


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
