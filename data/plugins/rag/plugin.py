# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from core.plugin_api import AppContext, Plugin, SettingField

class PluginImpl(Plugin):
    id = "rag"
    name = "RAG"
    version = "2.0.0"
    settings_schema = [SettingField("enabled", "Включить", "bool", True)]

    def on_load(self, app: AppContext) -> None:
        self.chunks = []
        try:
            cid = getattr(app.config, "ACTIVE_CHARACTER", "default")
            root = Path(getattr(app.config, "DATA_DIR", Path("data"))) / "personas" / "characters" / str(cid)
            for p in root.rglob("*.md"):
                try:
                    self.chunks.append(p.read_text(encoding="utf-8")[:1500])
                except Exception:
                    pass
            print(f"📚 rag: indexed chunks={len(self.chunks)}", flush=True)
        except Exception as e:
            print(f"rag: {e}", flush=True)

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not self.chunks or not messages:
            return messages
        block = "\n\n[RAG]\n" + "\n---\n".join(self.chunks[:3])
        if messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        return messages

def register():
    return PluginImpl()
