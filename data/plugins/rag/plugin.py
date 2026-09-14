# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from core.plugin_api import AppContext, Plugin, SettingField

_SKIP_NAMES = {"notes.md", "readme.md", "readme.txt"}


class PluginImpl(Plugin):
    id = "rag"
    name = "RAG"
    version = "2.1.0"
    settings_tab = "own"
    settings_tab_title = "RAG"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("max_chunks", "Кусков в prompt", "int", 3, min_value=1, max_value=20),
    ]

    def __init__(self) -> None:
        self.chunks: List[str] = []

    def on_load(self, app: AppContext) -> None:
        self._index(app)

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self._index(app)

    def _index(self, app: AppContext) -> None:
        self.chunks = []
        try:
            cid = (
                app.get_active_character()
                if hasattr(app, "get_active_character")
                else getattr(app.config, "ACTIVE_CHARACTER", "default")
            )
            root = Path(getattr(app.config, "DATA_DIR", Path("data"))) / "personas" / "characters" / str(cid)
            if not root.is_dir():
                return
            for p in sorted(root.rglob("*.md")):
                name = p.name.lower()
                if name in _SKIP_NAMES:
                    continue
                if "memory" in p.parts:
                    continue
                # карточку персонажа ядро и так кладёт в system
                if name in {"card.md", "character.md", "persona.md"}:
                    continue
                try:
                    text = p.read_text(encoding="utf-8")[:1500].strip()
                except Exception:
                    continue
                if text:
                    self.chunks.append(f"{p.stem}: {text}")
            print(f"📚 rag: {cid} chunks={len(self.chunks)}", flush=True)
        except Exception as e:
            print(f"rag: {e}", flush=True)

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not self.chunks or not messages:
            return messages
        n = int(app.get_plugin_setting(self.id, "max_chunks", 3) or 3)
        block = "\n\n[LORE]\n" + "\n---\n".join(self.chunks[: max(1, n)])
        if messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        return messages

def register():
    return PluginImpl()
