# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta
from core.plugin_api import AppContext, Plugin, SettingField

class PluginImpl(Plugin):
    id = "reminders"
    name = "Напоминания"
    version = "2.1.1"
    settings_tab = "own"
    settings_tab_title = "Напоминания"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
    ]

    def on_user_message(self, text, app):
        from core.plugin_api import HookResult
        low = (text or "").strip().lower()
        if low.startswith("напомни"):
            return HookResult(True, self.tool_add(app, text=text))
        if "напоминания" in low or "список напоминаний" in low:
            return HookResult(True, self.tool_list(app))
        return None

    def register_tools(self, app: AppContext) -> None:
        app.tools["reminder_add"] = self.tool_add
        app.tools["reminder_list"] = self.tool_list

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
            ("trigger_at", "REAL"), ("text", "TEXT"), ("updated_at", "REAL"),
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
        due_dt = datetime.now() + timedelta(hours=1)
        due = due_dt.isoformat(timespec="minutes")
        now = time.time()
        trigger = due_dt.timestamp()
        p = self._db(app)
        con = sqlite3.connect(str(p))
        info = con.execute("PRAGMA table_info(reminders)").fetchall()
        # (cid, name, type, notnull, dflt, pk)
        cols = [r[1] for r in info]
        notnull = {r[1] for r in info if r[3]}
        field_vals = {}
        if "text" in cols:
            field_vals["text"] = text
        if "due" in cols:
            field_vals["due"] = due
        if "done" in cols:
            field_vals["done"] = 0
        if "created_at" in cols:
            field_vals["created_at"] = now
        if "trigger_at" in cols:
            field_vals["trigger_at"] = trigger
        if "updated_at" in cols:
            field_vals["updated_at"] = now
        # любые notnull без значения
        for c in notnull:
            if c == "id":
                continue
            if c not in field_vals:
                if "INT" in str(next((r[2] for r in info if r[1]==c), "")).upper() or "REAL" in str(next((r[2] for r in info if r[1]==c), "")).upper():
                    field_vals[c] = now
                else:
                    field_vals[c] = text
        fields = list(field_vals.keys())
        values = [field_vals[f] for f in fields]
        sql = f"INSERT INTO reminders({','.join(fields)}) VALUES({','.join('?'*len(fields))})"
        try:
            con.execute(sql, values)
            con.commit()
        except Exception as e:
            con.close()
            return f"Не удалось создать напоминание: {e}"
        con.close()
        return f"Напоминание создано на ~1ч: {text}"

    def tool_list(self, app: AppContext, **kw) -> str:
        p = self._db(app)
        con = sqlite3.connect(str(p))
        cols = [r[1] for r in con.execute("PRAGMA table_info(reminders)").fetchall()]
        try:
            if "done" in cols and "due" in cols:
                rows = con.execute(
                    "SELECT id, text, due FROM reminders WHERE IFNULL(done,0)=0 ORDER BY id DESC LIMIT 20"
                ).fetchall()
            elif "due" in cols:
                rows = con.execute("SELECT id, text, due FROM reminders ORDER BY id DESC LIMIT 20").fetchall()
            else:
                rows = [(i, t, "") for i, t in con.execute(
                    "SELECT id, text FROM reminders ORDER BY id DESC LIMIT 20"
                ).fetchall()]
        except Exception as e:
            con.close()
            return f"Ошибка списка: {e}"
        con.close()
        if not rows:
            return "Активные напоминания:\nнет"
        return "Активные напоминания:\n" + "\n".join(f"#{i} {t} (до {d})" for i, t, d in rows)

def register():
    return PluginImpl()
