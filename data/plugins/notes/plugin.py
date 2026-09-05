# -*- coding: utf-8 -*-
"""Заметки персонажа (notes.md)."""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.plugin_api import AppContext, HookResult, Plugin, SettingField

_ADD = re.compile(r"(?i)(?:запиши|заметка|note)[:\s]+(.+)")
_LIST = re.compile(r"(?i)(покажи\s+заметк|список\s+замет|мои\s+заметк)")
_SEARCH = re.compile(r"(?i)(?:найди\s+в\s+заметк\w*|поиск\s+замет\w*)[:\s]+(.+)")


class PluginImpl(Plugin):
    id = "notes"
    name = "Заметки"
    version = "1.0.0"
    description = "Записки в notes.md у персонажа"
    settings_tab = "own"
    settings_tab_title = "Заметки"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
    ]

    def __init__(self):
        self.app: Optional[AppContext] = None
        self._lock = threading.Lock()

    def on_load(self, app: AppContext) -> None:
        self.app = app
        path = self._path(app)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_text("# Заметки\n\n", encoding="utf-8")
        print(f"📝 notes: {path}", flush=True)

    def on_character_changed(self, character_id, previous_id, app):
        self.app = app
        path = self._path(app)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_text("# Заметки\n\n", encoding="utf-8")

    def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        t = (text or "").strip()
        if _LIST.search(t):
            return HookResult(handled=True, response=self.list_notes(app))
        m = _SEARCH.search(t)
        if m:
            return HookResult(handled=True, response=self.search(app, m.group(1)))
        m = _ADD.search(t)
        if m:
            return HookResult(handled=True, response=self.add(app, m.group(1)))
        return None

    def on_before_llm(self, messages, app):
        """Лёгкий контекст из последних заметок, если спрашивают про «заметк»."""
        if not app.get_plugin_setting(self.id, "enabled", True) or not messages:
            return messages
        q = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                q = m["content"].lower()
                break
        if "заметк" not in q:
            return messages
        block = self.list_notes(app, limit=10)
        if messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + "\n\n" + block
        return messages

    def _path(self, app: AppContext) -> Path:
        try:
            return app.get_character_dir() / "notes.md"
        except Exception:
            base = Path(getattr(app.config, "DATA_DIR", Path(".")))
            return base / "notes.md"

    def add(self, app: AppContext, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "Пустая заметка."
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- [{stamp}] {text}\n"
        path = self._path(app)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        # в RAG / memory
        rag = app.plugins.get("rag")
        if rag is not None and hasattr(rag, "index_text"):
            try:
                rag.index_text(app, f"note: {text}")
            except Exception:
                pass
        return f"Заметка сохранена: {text[:80]}"

    def list_notes(self, app: AppContext, limit: int = 30) -> str:
        path = self._path(app)
        with self._lock:
            if not path.is_file():
                return "Заметок нет."
            lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("- ")]
        if not lines:
            return "Заметок пока нет."
        return "Заметки:\n" + "\n".join(lines[-limit:])

    def search(self, app: AppContext, query: str, limit: int = 15) -> str:
        q = (query or "").strip().lower()
        if not q:
            return self.list_notes(app, limit)
        path = self._path(app)
        with self._lock:
            lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("- ")]
        hits = [ln for ln in lines if q in ln.lower()]
        if not hits:
            return f"По «{query}» ничего не найдено."
        return "Найдено:\n" + "\n".join(hits[-limit:])


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
