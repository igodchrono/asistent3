# -*- coding: utf-8 -*-
"""Memory tools: memory_add / list / forget + inject profile in prompt."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

MemoryStore = None  # type: ignore
try:
    from plugins.memory.store import CharacterMemoryStore as _MS
    MemoryStore = _MS
except Exception:
    try:
        from plugins.memory.store import MemoryStore as _MS
        MemoryStore = _MS
    except Exception:
        try:
            from .store import CharacterMemoryStore as _MS
            MemoryStore = _MS
        except Exception as _e:
            print(f"memory: store import failed: {_e}", flush=True)


class PluginImpl(Plugin):
    id = "memory"
    name = "Память персонажа"
    version = "2.0.0"
    description = "Долговременная память (tools + inject)."
    settings_tab = "own"
    settings_tab_title = "Память"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("max_inject", "Фактов в prompt", "int", 12, min_value=1, max_value=50),
    ]

    def __init__(self) -> None:
        self.store = None
        self.app = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        self._open_store(app)

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self._open_store(app)

    def _open_store(self, app: AppContext) -> None:
        if MemoryStore is None:
            print("memory: no MemoryStore", flush=True)
            return
        try:
            if self.store is not None:
                try:
                    self.store.close()
                except Exception:
                    pass
            cid = (
                app.get_active_character()
                if hasattr(app, "get_active_character")
                else getattr(app.config, "ACTIVE_CHARACTER", "default")
            )
            root = Path(getattr(app.config, "DATA_DIR", Path("data")))
            char_dir = root / "personas" / "characters" / str(cid)
            char_dir.mkdir(parents=True, exist_ok=True)
            self.store = MemoryStore(char_dir, character_id=str(cid))
            n = self.store.count() if hasattr(self.store, "count") else "?"
            print(f"🧠 memory: {cid} → {self.store.db_path} (n={n})", flush=True)
        except Exception as e:
            print(f"memory: open failed: {e}", flush=True)
            self.store = None

    def register_tools(self, app: AppContext) -> None:
        app.tools["memory_add"] = self.tool_add
        app.tools["memory_list"] = self.tool_list
        app.tools["memory_forget"] = self.tool_forget

    def tool_add(self, app: AppContext, text: str = "", **kwargs) -> str:
        text = (text or kwargs.get("query") or "").strip()
        if not text:
            return "Нечего запоминать — пустой текст."
        if self.store is None:
            self._open_store(app)
        if self.store is None:
            return "Память недоступна."
        try:
            mid = self.store.add(text, category="longterm")
            cid = getattr(app.config, "ACTIVE_CHARACTER", "")
            return f"Записала в память «{cid}» (#{mid}): {text}"
        except Exception as e:
            # reopen
            self._open_store(app)
            try:
                mid = self.store.add(text, category="longterm")
                return f"Записала в память (#{mid}): {text}"
            except Exception as e2:
                return f"Не удалось записать: {e2}"

    def tool_list(self, app: AppContext, **kwargs) -> str:
        if self.store is None:
            self._open_store(app)
        if self.store is None:
            return "Память недоступна."
        try:
            items = self.store.list_all(limit=20)
        except Exception as e:
            self._open_store(app)
            try:
                items = self.store.list_all(limit=20)
            except Exception as e2:
                return f"Ошибка чтения: {e2}"
        if not items:
            return "Долговременная память пока пустая."
        cid = getattr(app.config, "ACTIVE_CHARACTER", "")
        lines = [f"Долговременная память «{cid}»: {len(items)}"]
        for it in items:
            lines.append(f"📌 #{it.get('id')} {it.get('content') or it.get('text') or ''}")
        return "\n".join(lines)

    def tool_forget(self, app: AppContext, text: str = "", **kwargs) -> str:
        text = (text or kwargs.get("query") or "").strip()
        if self.store is None:
            self._open_store(app)
        if self.store is None:
            return "Память недоступна."
        if not text:
            return "Укажи, что забыть."
        try:
            items = self.store.list_all(limit=100)
            deleted = 0
            low = text.lower()
            for it in items:
                content = str(it.get("content") or it.get("text") or "")
                if low in content.lower() or content.lower() in low:
                    if self.store.delete(int(it["id"])):
                        deleted += 1
            return f"Удалила записей: {deleted}." if deleted else "Ничего подходящего не нашла."
        except Exception as e:
            return f"Ошибка удаления: {e}"


    def on_user_message(self, text: str, app: AppContext):
        from core.plugin_api import HookResult
        low = (text or "").strip().lower()
        if low.startswith("запомни:") or low.startswith("запомни "):
            body = text.split(":", 1)[-1].strip() if ":" in text else text.split(" ", 1)[-1]
            return HookResult(True, self.tool_add(app, text=body))
        if "что ты помнишь" in low or low in ("память", "что помнишь"):
            return HookResult(True, self.tool_list(app))
        if low.startswith("забудь"):
            body = text.split(" ", 1)[-1] if " " in text else ""
            body = body.replace("про ", "").strip()
            return HookResult(True, self.tool_forget(app, text=body))
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if self.store is None:
            self._open_store(app)
        if self.store is None:
            return messages
        try:
            items = self.store.list_all(limit=int(app.get_plugin_setting(self.id, "max_inject", 12) or 12))
        except Exception:
            try:
                self._open_store(app)
                items = self.store.list_all(limit=12)
            except Exception:
                return messages
        if not items:
            return messages
        block = "\n".join(
            f"- {it.get('content') or it.get('text')}" for it in items
        )
        inj = f"\n\n[ПАМЯТЬ ПЕРСОНАЖА]\n{block}\n"
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + inj
        return messages


def register():
    return PluginImpl()
