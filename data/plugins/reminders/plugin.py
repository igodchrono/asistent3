# -*- coding: utf-8 -*-
"""Напоминания: SQLite + UI список/добавить/удалить."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from core.plugin_api import AppContext, HookResult, Plugin, SettingField


class PluginImpl(Plugin):
    id = "reminders"
    name = "Напоминания"
    version = "2.2.0"
    settings_tab = "own"
    settings_tab_title = "Напоминания"
    settings_schema = [SettingField("enabled", "Включить", "bool", True)]

    def __init__(self) -> None:
        self._ui: Dict[str, Any] = {}
        self.app = None

    def on_user_message(self, text, app):
        low = (text or "").strip().lower()
        if low.startswith("напомни"):
            return HookResult(True, self.tool_add(app, text=text))
        if "напоминания" in low or "список напоминаний" in low:
            return HookResult(True, self.tool_list(app))
        return None

    def register_tools(self, app: AppContext) -> None:
        app.tools["reminder_add"] = self.tool_add
        app.tools["reminder_list"] = self.tool_list
        app.tools["reminder_delete"] = self.tool_delete

    def _db(self, app: AppContext) -> Path:
        root = Path(getattr(app.config, "DATA_DIR", Path("data")))
        p = root / "reminders.db"
        con = sqlite3.connect(str(p))
        con.execute(
            "CREATE TABLE IF NOT EXISTS reminders ("
            "id INTEGER PRIMARY KEY, text TEXT, due TEXT, "
            "done INTEGER DEFAULT 0, created_at REAL, trigger_at REAL)"
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(reminders)").fetchall()}
        for col, typ in (
            ("due", "TEXT"), ("done", "INTEGER"), ("created_at", "REAL"),
            ("trigger_at", "REAL"), ("text", "TEXT"),
        ):
            if col not in cols:
                try:
                    con.execute(f"ALTER TABLE reminders ADD COLUMN {col} {typ}")
                except Exception:
                    pass
        con.commit()
        con.close()
        return p

    def tool_add(self, app: AppContext, text: str = "", **kw) -> str:
        text = (text or kw.get("query") or "").strip() or "напоминание"
        # убрать слово напомни
        import re
        text = re.sub(r"^\s*напомни(ть)?\s*", "", text, flags=re.I).strip() or text
        due_dt = datetime.now() + timedelta(hours=1)
        due = due_dt.isoformat(timespec="minutes")
        now = time.time()
        trigger = due_dt.timestamp()
        p = self._db(app)
        con = sqlite3.connect(str(p))
        try:
            con.execute(
                "INSERT INTO reminders(text, due, done, created_at, trigger_at) VALUES(?,?,0,?,?)",
                (text, due, now, trigger),
            )
            con.commit()
        except Exception as e:
            con.close()
            return f"Не удалось создать напоминание: {e}"
        con.close()
        self._refresh_ui(app)
        return f"Напоминание создано на ~1ч: {text}"

    def tool_list(self, app: AppContext, **kw) -> str:
        rows = self._rows(app)
        if not rows:
            return "Активные напоминания:\nнет"
        return "Активные напоминания:\n" + "\n".join(f"#{i} {t} (до {d})" for i, t, d in rows)

    def tool_delete(self, app: AppContext, text: str = "", id: int = 0, **kw) -> str:
        p = self._db(app)
        con = sqlite3.connect(str(p))
        n = 0
        try:
            if id:
                con.execute("DELETE FROM reminders WHERE id=?", (int(id),))
                n = con.total_changes
            elif text:
                con.execute("DELETE FROM reminders WHERE text LIKE ?", (f"%{text}%",))
                n = con.total_changes
            con.commit()
        except Exception as e:
            con.close()
            return f"Ошибка удаления: {e}"
        con.close()
        self._refresh_ui(app)
        return f"Удалено напоминаний: {n}"

    def _rows(self, app: AppContext):
        p = self._db(app)
        con = sqlite3.connect(str(p))
        try:
            rows = con.execute(
                "SELECT id, text, IFNULL(due,'') FROM reminders WHERE IFNULL(done,0)=0 ORDER BY id DESC LIMIT 50"
            ).fetchall()
        except Exception:
            rows = []
        con.close()
        return rows

    def setup_settings_tab(self, tab, app: AppContext) -> bool:
        try:
            from PyQt5 import QtWidgets, QtCore
        except ImportError:
            return False
        self.app = app
        layout = tab.layout() or QtWidgets.QVBoxLayout(tab)
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        layout.addWidget(QtWidgets.QLabel("<b>Напоминания</b>"))
        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._ui["list"] = lst
        layout.addWidget(lst, 1)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("Обновить")
        b2 = QtWidgets.QPushButton("Удалить выбранные")
        b3 = QtWidgets.QPushButton("Добавить…")
        row.addWidget(b1); row.addWidget(b2); row.addWidget(b3)
        layout.addLayout(row)

        def refresh():
            self._refresh_ui(app)

        def delete_sel():
            ids = []
            for it in list(lst.selectedItems()):
                try:
                    mid = it.data(QtCore.Qt.UserRole)
                except RuntimeError:
                    continue
                if mid is not None:
                    ids.append(int(mid))
            n = 0
            for mid in ids:
                self.tool_delete(app, id=mid)
                n += 1
            refresh()
            QtWidgets.QMessageBox.information(tab, "Напоминания", f"Удалено: {n}")

        def add():
            text, ok = QtWidgets.QInputDialog.getText(tab, "Напоминания", "Текст (через ~1ч):")
            if ok and text.strip():
                self.tool_add(app, text=text.strip())
                refresh()

        b1.clicked.connect(refresh)
        b2.clicked.connect(delete_sel)
        b3.clicked.connect(add)
        refresh()
        return True

    def collect_settings_tab(self) -> Dict[str, Any]:
        return {}

    def _refresh_ui(self, app: Optional[AppContext] = None) -> None:
        lst = self._ui.get("list")
        if lst is None:
            return
        app = app or self.app
        if app is None:
            return
        try:
            from PyQt5 import QtCore, QtWidgets
        except ImportError:
            return
        lst.clear()
        rows = self._rows(app)
        if not rows:
            lst.addItem("(пусто)")
            return
        for i, t, d in rows:
            it = QtWidgets.QListWidgetItem(f"#{i}  {t}  (до {d})")
            it.setData(QtCore.Qt.UserRole, i)
            lst.addItem(it)


def register():
    return PluginImpl()
