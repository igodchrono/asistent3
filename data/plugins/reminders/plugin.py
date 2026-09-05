# -*- coding: utf-8 -*-
"""Напоминания через чат + SQLite + таймер."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

from core.plugin_api import AppContext, HookResult, Plugin, SettingField

_RE_IN = re.compile(
    r"(?i)напомин\w*\s+(?:мне\s+)?(?:через\s+)?(\d+)\s*(секунд|сек|минут|мин|час|часа|часов)\s*(?:о\s+том[,]?\s*что\s+|что\s+|:\s*)?(.+)",
)
_RE_LIST = re.compile(r"(?i)(список\s+напомин|какие\s+напомин|напомин\w*\s+список)")
_RE_CANCEL = re.compile(r"(?i)(отмени|удали)\s+напомин\w*\s*#?(\d+)?")


class PluginImpl(Plugin):
    id = "reminders"
    name = "Напоминания"
    version = "1.0.0"
    description = "Напомни через N минут/часов"
    settings_tab = "own"
    settings_tab_title = "Напоминания"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("check_interval_sec", "Проверка каждые (сек)", "int", 5, min_value=2, max_value=60),
    ]

    def __init__(self):
        self.app: Optional[AppContext] = None
        self.db_path: Optional[Path] = None
        self._lock = threading.Lock()
        self._timer = None
        self._items: List[dict] = []

    def on_load(self, app: AppContext) -> None:
        self.app = app
        base = Path(getattr(app.config, "DATA_DIR", Path(".")))
        self.db_path = base / "reminders.db"
        self._init_db()
        self._load()
        self._start_timer(app)
        print(f"⏰ reminders: {self.db_path} active={len(self._items)}", flush=True)

    def on_shutdown(self, app: AppContext) -> None:
        if self._timer:
            try:
                self._timer.stop()
                self._timer.deleteLater()
            except Exception:
                pass
            self._timer = None

    def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        t = (text or "").strip()
        if _RE_LIST.search(t):
            lines = self.list_active()
            msg = "Активные напоминания:\n" + ("\n".join(lines) if lines else "нет")
            return HookResult(handled=True, response=msg)
        m = _RE_CANCEL.search(t)
        if m:
            rid = int(m.group(2)) if m.group(2) else None
            ok = self.cancel(rid)
            return HookResult(handled=True, response="Напоминание отменено." if ok else "Не найдено.")
        m = _RE_IN.search(t)
        if m:
            n = int(m.group(1))
            unit = m.group(2).lower()
            body = (m.group(3) or "напоминание").strip()
            mult = 1
            if unit.startswith("мин"):
                mult = 60
            elif unit.startswith("час"):
                mult = 3600
            seconds = n * mult
            rid = self.add(body, seconds)
            human = f"{n} {unit}"
            return HookResult(
                handled=True,
                response=f"Хорошо, напомню через {human}: «{body}» (#{rid})",
            )
        return None

    def add(self, text: str, seconds: int) -> int:
        assert self.db_path
        trigger = datetime.now() + timedelta(seconds=seconds)
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO reminders (text, created_at, trigger_at, seconds, is_active, is_done) VALUES (?,?,?,?,1,0)",
                (text, datetime.now().isoformat(), trigger.isoformat(), seconds),
            )
            conn.commit()
            rid = int(cur.lastrowid)
            conn.close()
            self._items.append({"id": rid, "text": text, "time": time.time() + seconds})
            return rid

    def list_active(self) -> List[str]:
        now = time.time()
        out = []
        for r in list(self._items):
            left = max(0, int(r["time"] - now))
            out.append(f"#{r['id']}: {r['text']} (через {left} сек)")
        return out

    def cancel(self, rid: Optional[int]) -> bool:
        if rid is None and self._items:
            rid = self._items[-1]["id"]
        if rid is None:
            return False
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("UPDATE reminders SET is_active=0 WHERE id=?", (rid,))
            conn.commit()
            conn.close()
            before = len(self._items)
            self._items = [r for r in self._items if r["id"] != rid]
            return len(self._items) < before

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                trigger_at TEXT NOT NULL,
                seconds INTEGER,
                is_active INTEGER DEFAULT 1,
                is_done INTEGER DEFAULT 0
            )"""
        )
        conn.commit()
        conn.close()

    def _load(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT id, text, trigger_at FROM reminders WHERE is_active=1 AND is_done=0"
        ).fetchall()
        conn.close()
        now = datetime.now()
        self._items = []
        for rid, text, trigger_at in rows:
            try:
                ts = datetime.fromisoformat(trigger_at)
                if ts > now:
                    self._items.append({"id": rid, "text": text, "time": ts.timestamp()})
            except Exception:
                pass

    def _start_timer(self, app: AppContext) -> None:
        try:
            from PyQt5 import QtCore
        except ImportError:
            return
        self._timer = QtCore.QTimer()
        sec = int(app.get_plugin_setting(self.id, "check_interval_sec", 5) or 5)
        self._timer.timeout.connect(lambda: self._tick(app))
        self._timer.start(max(2, sec) * 1000)

    def _tick(self, app: AppContext) -> None:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        now = time.time()
        due = []
        with self._lock:
            for r in list(self._items):
                if now >= r["time"]:
                    due.append(r)
                    self._items.remove(r)
        for r in due:
            try:
                conn = sqlite3.connect(str(self.db_path))
                conn.execute("UPDATE reminders SET is_done=1 WHERE id=?", (r["id"],))
                conn.commit()
                conn.close()
            except Exception:
                pass
            msg = f"⏰ Напоминание: {r['text']}"
            window = getattr(app, "window", None)
            if window is not None and hasattr(window, "publish_assistant_message"):
                try:
                    window.publish_assistant_message(msg)
                except Exception:
                    print(msg, flush=True)
            else:
                print(msg, flush=True)
            # эмоция
            emo = app.plugins.get("emotion")
            if emo is not None and hasattr(emo, "set_context"):
                try:
                    emo.set_context(app, "surprised", "reminder")
                except Exception:
                    pass


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
