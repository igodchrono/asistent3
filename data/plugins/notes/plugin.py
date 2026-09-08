# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from typing import Any
from core.plugin_api import AppContext, Plugin, SettingField

class PluginImpl(Plugin):
    id = "notes"
    name = "Заметки"
    version = "2.0.0"
    settings_tab = "own"
    settings_tab_title = "Заметки"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
    ]

    def on_user_message(self, text, app):
        from core.plugin_api import HookResult
        low = (text or "").strip().lower()
        if low.startswith("запиши:") or low.startswith("запиши "):
            body = text.split(":", 1)[-1].strip() if ":" in text else text.split(" ", 1)[-1]
            return HookResult(True, self.tool_add(app, text=body))
        if "покажи заметки" in low or low == "заметки":
            return HookResult(True, self.tool_list(app))
        if low.startswith("найди в заметках"):
            q = text.split("заметках", 1)[-1].strip()
            return HookResult(True, self.tool_find(app, text=q))
        return None

    def register_tools(self, app: AppContext) -> None:
        app.tools["note_add"] = self.tool_add
        app.tools["note_list"] = self.tool_list
        app.tools["note_find"] = self.tool_find

    def _path(self, app: AppContext) -> Path:
        cid = getattr(app.config, "ACTIVE_CHARACTER", "default")
        root = Path(getattr(app.config, "DATA_DIR", Path("data")))
        p = root / "personas" / "characters" / str(cid) / "notes.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")
        return p

    def tool_add(self, app: AppContext, text: str = "", **kw) -> str:
        text = (text or kw.get("query") or "").strip()
        if not text:
            return "Пустая заметка."
        p = self._path(app)
        line = f"- [{datetime.now():%Y-%m-%d %H:%M}] {text}\n"
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
        return f"Заметка сохранена: {text}"

    def tool_list(self, app: AppContext, **kw) -> str:
        p = self._path(app)
        body = p.read_text(encoding="utf-8").strip()
        return "Заметки:\n" + body if body else "Заметок нет."

    def tool_find(self, app: AppContext, text: str = "", **kw) -> str:
        q = (text or kw.get("query") or "").strip().lower()
        p = self._path(app)
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if q in ln.lower()]
        return "Найдено:\n" + "\n".join(lines) if lines else "Ничего не найдено."

def register():
    return PluginImpl()
