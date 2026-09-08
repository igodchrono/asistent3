# -*- coding: utf-8 -*-
"""Memory tools + вкладка настроек: список фактов, удаление."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, HookResult, Plugin, SettingField

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
    version = "2.1.0"
    description = "Долговременная память (tools + UI списка)."
    settings_tab = "own"
    settings_tab_title = "Память"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("max_inject", "Фактов в prompt", "int", 12, min_value=1, max_value=50),
    ]

    def __init__(self) -> None:
        self.store = None
        self.app = None
        self._ui = {}  # widgets for settings tab

    def on_load(self, app: AppContext) -> None:
        self.app = app
        self._open_store(app)

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self._open_store(app)
        self._refresh_list_ui()

    def _open_store(self, app: AppContext) -> None:
        if MemoryStore is None:
            print("memory: no MemoryStore", flush=True)
            self.store = None
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

    # ---- tools ----
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
            self._refresh_list_ui()
            return f"Записала в память «{cid}» (#{mid}): {text}"
        except Exception as e:
            self._open_store(app)
            try:
                mid = self.store.add(text, category="longterm")
                self._refresh_list_ui()
                return f"Записала в память (#{mid}): {text}"
            except Exception as e2:
                return f"Не удалось записать: {e2}"

    def tool_list(self, app: AppContext, **kwargs) -> str:
        if self.store is None:
            self._open_store(app)
        if self.store is None:
            return "Память недоступна."
        try:
            items = self.store.list_all(limit=50)
        except Exception:
            self._open_store(app)
            try:
                items = self.store.list_all(limit=50)
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
            items = self.store.list_all(limit=200)
            deleted = 0
            low = text.lower()
            # "только beta" / id
            only = low.replace("только", "").replace("про", "").strip()
            for it in items:
                content = str(it.get("content") or it.get("text") or "")
                if only and only in content.lower():
                    if self.store.delete(int(it["id"])):
                        deleted += 1
                elif low in content.lower() or content.lower() in low:
                    if self.store.delete(int(it["id"])):
                        deleted += 1
            self._refresh_list_ui()
            return f"Удалила записей: {deleted}." if deleted else "Ничего подходящего не нашла."
        except Exception as e:
            return f"Ошибка удаления: {e}"

    def on_user_message(self, text: str, app: AppContext):
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
        block = "\n".join(f"- {it.get('content') or it.get('text')}" for it in items)
        inj = f"\n\n[ПАМЯТЬ ПЕРСОНАЖА]\n{block}\n"
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + inj
        return messages

    # ---- Settings UI: список + удаление ----
    def setup_settings_tab(self, tab, app: AppContext) -> bool:
        try:
            from PyQt5 import QtWidgets, QtCore
        except ImportError:
            return False
        self.app = app
        if self.store is None:
            self._open_store(app)

        # clear tab
        if tab.layout() is not None:
            while tab.layout().count():
                item = tab.layout().takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            layout = tab.layout()
        else:
            layout = QtWidgets.QVBoxLayout(tab)

        cid = getattr(app.config, "ACTIVE_CHARACTER", "?")
        layout.addWidget(QtWidgets.QLabel(
            f"<b>Долговременная память</b> — персонаж: <code>{cid}</code><br>"
            f"Путь: <code>{getattr(getattr(self, 'store', None), 'db_path', '—')}</code>"
        ))

        # schema fields
        form = QtWidgets.QFormLayout()
        values = {}
        try:
            from plugin_catalog import plugin_settings_block
            values = plugin_settings_block(self.id) or {}
        except Exception:
            pass
        self._ui = {}
        for field in self.settings_schema:
            key = field.key
            val = values.get(key, field.default)
            if field.type == "bool":
                w = QtWidgets.QCheckBox(field.label)
                w.setChecked(bool(val))
            elif field.type == "int":
                w = QtWidgets.QSpinBox()
                if field.min_value is not None:
                    w.setMinimum(int(field.min_value))
                if field.max_value is not None:
                    w.setMaximum(int(field.max_value))
                w.setValue(int(val if val is not None else field.default or 0))
            else:
                w = QtWidgets.QLineEdit(str(val or ""))
            self._ui[key] = w
            form.addRow(field.label if field.type != "bool" else "", w)
        layout.addLayout(form)

        layout.addWidget(QtWidgets.QLabel("<b>Записи в памяти</b> (текущий персонаж):"))
        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._ui["list"] = lst
        layout.addWidget(lst, 1)

        row = QtWidgets.QHBoxLayout()
        btn_ref = QtWidgets.QPushButton("Обновить")
        btn_del = QtWidgets.QPushButton("Удалить выбранные")
        btn_clear = QtWidgets.QPushButton("Очистить всё")
        btn_add = QtWidgets.QPushButton("Добавить…")
        row.addWidget(btn_ref)
        row.addWidget(btn_del)
        row.addWidget(btn_clear)
        row.addWidget(btn_add)
        layout.addLayout(row)

        def refresh():
            self._refresh_list_ui()

        def delete_selected():
            if self.store is None:
                return
            items = lst.selectedItems()
            n = 0
            for it in items:
                mid = it.data(QtCore.Qt.UserRole)
                if mid is not None:
                    try:
                        if self.store.delete(int(mid)):
                            n += 1
                    except Exception as e:
                        print(f"memory ui delete: {e}", flush=True)
            refresh()
            QtWidgets.QMessageBox.information(tab, "Память", f"Удалено: {n}")

        def clear_all():
            if self.store is None:
                return
            r = QtWidgets.QMessageBox.question(
                tab, "Память", "Удалить ВСЕ записи этого персонажа?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if r != QtWidgets.QMessageBox.Yes:
                return
            try:
                if hasattr(self.store, "clear"):
                    n = self.store.clear(only_unpinned=False)
                else:
                    n = 0
                    for it in self.store.list_all(limit=5000):
                        if self.store.delete(int(it["id"])):
                            n += 1
            except Exception as e:
                QtWidgets.QMessageBox.warning(tab, "Память", str(e))
                return
            refresh()
            QtWidgets.QMessageBox.information(tab, "Память", f"Очищено: {n}")

        def add_fact():
            text, ok = QtWidgets.QInputDialog.getText(tab, "Память", "Новый факт:")
            if ok and text.strip():
                self.tool_add(app, text=text.strip())
                refresh()

        btn_ref.clicked.connect(refresh)
        btn_del.clicked.connect(delete_selected)
        btn_clear.clicked.connect(clear_all)
        btn_add.clicked.connect(add_fact)
        refresh()
        return True

    def collect_settings_tab(self) -> Dict[str, Any]:
        out = {}
        for field in self.settings_schema:
            w = self._ui.get(field.key)
            if w is None:
                continue
            if field.type == "bool":
                out[field.key] = w.isChecked()
            elif field.type == "int":
                out[field.key] = w.value()
            else:
                out[field.key] = w.text()
        return out

    def _refresh_list_ui(self) -> None:
        lst = self._ui.get("list")
        if lst is None:
            return
        try:
            from PyQt5 import QtCore, QtWidgets
        except ImportError:
            return
        lst.clear()
        if self.store is None and self.app is not None:
            self._open_store(self.app)
        if self.store is None:
            lst.addItem("(память недоступна)")
            return
        try:
            items = self.store.list_all(limit=200)
        except Exception as e:
            lst.addItem(f"(ошибка: {e})")
            return
        if not items:
            lst.addItem("(пусто)")
            return
        for it in items:
            mid = it.get("id")
            content = it.get("content") or it.get("text") or ""
            row = QtWidgets.QListWidgetItem(f"#{mid}  {content}")
            row.setData(QtCore.Qt.UserRole, mid)
            lst.addItem(row)


def register():
    return PluginImpl()
