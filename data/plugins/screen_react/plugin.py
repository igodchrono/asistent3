# -*- coding: utf-8 -*-
"""Фон: заголовок окна → context в state (не парсит фразы)."""
from __future__ import annotations
import time
from typing import Any, Dict, List
from core.plugin_api import AppContext, Plugin, SettingField

class PluginImpl(Plugin):
    id = "screen_react"
    name = "Реакция на экран"
    version = "2.0.0"
    settings_tab = "own"
    settings_tab_title = "Реакция на экран"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("interval_sec", "Интервал опроса (сек)", "int", 4, min_value=2, max_value=30),
    ]

    def on_load(self, app: AppContext) -> None:
        self._timer = None
        self.app = app
        try:
            from PyQt5 import QtCore
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(lambda: self._tick(app))
            sec = int(app.get_plugin_setting(self.id, "interval_sec", 4) or 4)
            self._timer.start(max(2, sec) * 1000)
            print("👁 screen_react 2.0: context only", flush=True)
        except Exception as e:
            print(f"screen_react: no timer {e}", flush=True)

    def on_shutdown(self, app: AppContext) -> None:
        if self._timer:
            self._timer.stop()

    def _tick(self, app: AppContext) -> None:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        title = self._fg_title()
        if not title:
            return
        app.state["screen_react_title"] = title
        app.state["screen_react_context"] = title
        # лёгкий mood
        low = title.lower()
        if any(w in low for w in ("nsfw", "hentai", "18+", "xxx", "porno")):
            if app.state.get("character_nsfw") is False:
                emo, conf = "shy", 0.75
            else:
                emo, conf = "flirty", 0.8
        elif any(w in low for w in ("chrome", "google", "поиск", "search")):
            emo, conf = "searching", 0.7
        elif any(w in low for w in ("code", "visual studio", "pycharm", "cmd")):
            emo, conf = "thinking", 0.7
        else:
            print("screen_react: skip conf=0.00", flush=True)
            return
        app.state["screen_react_emotion"] = emo
        print(f"screen_react: {emo}/{emo} conf={conf:.2f} ← {title[:80]!r}", flush=True)
        pl = app.plugins.get("emotion")
        if pl and hasattr(pl, "set_context"):
            try:
                pl.set_context(app, emo, "screen_react")
            except Exception:
                pass

    def _infer(self, app, ctx):
        """Совместимость с selftest: (emotion, anim, conf)."""
        text = ""
        nsfw_allowed = None
        if isinstance(ctx, dict):
            text = str(ctx.get("title") or "") + " " + str(ctx.get("text") or "")
            if "nsfw" in ctx:
                nsfw_allowed = bool(ctx.get("nsfw"))
            if "card_nsfw" in ctx:
                nsfw_allowed = bool(ctx.get("card_nsfw"))
            if "nsfw_allowed" in ctx:
                nsfw_allowed = bool(ctx.get("nsfw_allowed"))
            cid = ctx.get("character") or ctx.get("character_id")
            if cid is not None and nsfw_allowed is None:
                try:
                    from character_catalog import read_character_card
                    card = (read_character_card(str(cid)) or "").lower()
                    nsfw_allowed = any(x in card for x in ("nsfw", "18+", "эрот"))
                except Exception:
                    pass
        else:
            text = str(ctx or "")
        if nsfw_allowed is None and app is not None:
            if "character_nsfw" in app.state:
                nsfw_allowed = bool(app.state.get("character_nsfw"))
            else:
                try:
                    cid = getattr(app.config, "ACTIVE_CHARACTER", "") or ""
                    from character_catalog import read_character_card
                    card = (read_character_card(str(cid)) or "").lower()
                    nsfw_allowed = any(x in card for x in ("nsfw", "18+", "эрот"))
                    app.state["character_nsfw"] = nsfw_allowed
                except Exception:
                    nsfw_allowed = True
        if nsfw_allowed is None:
            nsfw_allowed = True
        low = text.lower()
        if any(w in low for w in ("nsfw", "hentai", "18+", "xxx", "porno", "секс")):
            if not nsfw_allowed:
                return "shy", "shy", 0.75
            return "flirty", "flirty", 0.85
        if any(w in low for w in ("chrome", "google", "поиск", "search")):
            return "searching", "searching", 0.72
        if any(w in low for w in ("code", "cmd", "visual studio", "pycharm")):
            return "thinking", "thinking", 0.7
        return "neutral", "idle", 0.4

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        title = str(app.state.get("screen_react_title") or "")
        if not title or not messages:
            return messages
        block = f"\n\n[ЭКРАН СЕЙЧАС] активное окно: {title}\n"
        if messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        return messages

    @staticmethod
    def _fg_title() -> str:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return (buf.value or "").strip()
        except Exception:
            return ""

def register():
    return PluginImpl()
