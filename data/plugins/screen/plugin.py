# -*- coding: utf-8 -*-
"""screen = screen_vision + screen_react."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from core.plugin_api import AppContext, Plugin, SettingField

# reuse helpers from original vision if present
try:
    from plugins.screen.vision import list_monitors
except Exception:
    def list_monitors():
        return []

class PluginImpl(Plugin):
    id = "screen"
    name = "Экран (зрение + реакция)"
    version = "1.0.0"
    description = "Снимок монитора + фон по заголовку окна"
    settings_tab = "own"
    settings_tab_title = "Экран"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("react", "Реакция на активное окно", "bool", True),
        SettingField("interval_sec", "Интервал опроса (сек)", "int", 4, min_value=2, max_value=30),
        SettingField("max_side", "Макс. сторона снимка (px)", "int", 1600, min_value=640, max_value=3840),
        SettingField("monitor", "Индекс монитора", "int", 1, min_value=0, max_value=8),
    ]

    def __init__(self):
        self._timer = None
        self.app = None
        self._vision = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.plugins["screen_vision"] = self
        app.plugins["screen_react"] = self
        print("👁 screen 1.0: vision+react", flush=True)
        # wrap original vision tools if folder still exists
        try:
            from plugins.screen.vision import PluginImpl as Vision
            self._vision = Vision()
            if hasattr(self._vision, "on_load"):
                try:
                    self._vision.on_load(app)
                except Exception:
                    pass
        except Exception as e:
            print(f"screen: vision helper {e}", flush=True)
        try:
            from PyQt5 import QtCore
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(lambda: self._tick(app))
            sec = int(app.get_plugin_setting(self.id, "interval_sec", 4) or 4)
            self._timer.start(max(2, sec) * 1000)
        except Exception as e:
            print(f"screen: no timer {e}", flush=True)

    def on_shutdown(self, app: AppContext) -> None:
        if self._timer:
            self._timer.stop()

    def register_tools(self, app: AppContext) -> None:
        app.tools["describe_screen"] = self.tool_describe_screen
        if self._vision and hasattr(self._vision, "register_tools"):
            try:
                self._vision.register_tools(app)
            except Exception:
                pass

    def tool_describe_screen(self, app: AppContext, **kwargs) -> str:
        if self._vision and hasattr(self._vision, "tool_describe_screen"):
            return self._vision.tool_describe_screen(app, **kwargs)
        return "screen: vision-модуль не загружен (нужен plugins/screen_vision)"

    def capture(self, app: AppContext):
        if self._vision and hasattr(self._vision, "capture"):
            return self._vision.capture(app)
        return None

    def _tick(self, app: AppContext) -> None:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        if not app.get_plugin_setting(self.id, "react", True):
            return
        title = self._fg_title()
        if not title:
            return
        app.state["screen_react_title"] = title
        app.state["screen_react_context"] = title
        emo, anim, conf = self._infer(app, title)
        if conf < 0.5:
            return
        app.state["screen_react_emotion"] = emo
        print(f"screen: {emo}/{anim} conf={conf:.2f} ← {title[:70]!r}", flush=True)
        persona = app.plugins.get("persona") or app.plugins.get("emotion")
        if persona and hasattr(persona, "set_context"):
            try:
                persona.set_context(app, emo, "screen")
            except Exception:
                pass

    def _infer(self, app, ctx):
        text = str(ctx or "")
        nsfw_allowed = app.state.get("character_nsfw") if app is not None else True
        if nsfw_allowed is None:
            nsfw_allowed = True
        low = text.lower()
        if any(w in low for w in ("nsfw", "hentai", "18+", "xxx", "porno", "секс")):
            if not nsfw_allowed:
                return "shy", "shy", 0.75
            return "flirty", "flirty", 0.85
        if any(w in low for w in ("chrome", "google", "поиск", "search")):
            return "searching", "thinking", 0.7
        if any(w in low for w in ("code", "cmd", "visual studio", "pycharm")):
            return "thinking", "thinking", 0.7
        return "neutral", "idle", 0.4

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        title = str(app.state.get("screen_react_title") or "")
        desc = str(app.state.get("screen_vision_last_desc") or "")
        bits = []
        if title:
            bits.append(f"активное окно: {title}")
        if desc:
            bits.append(f"снимок: {desc[:200]}")
        if not bits or not messages:
            return messages
        block = "\n\n[ЭКРАН] " + " | ".join(bits) + "\n"
        if messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        if self._vision and hasattr(self._vision, "on_before_llm"):
            try:
                messages = self._vision.on_before_llm(messages, app)
            except Exception:
                pass
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        if self._vision and hasattr(self._vision, "on_after_llm"):
            try:
                return self._vision.on_after_llm(reply, app)
            except Exception:
                pass
        return reply

    def setup_settings_tab(self, tab, app: AppContext) -> bool:
        if self._vision and hasattr(self._vision, "setup_settings_tab"):
            return self._vision.setup_settings_tab(tab, app)
        return False

    def collect_settings_tab(self):
        if self._vision and hasattr(self._vision, "collect_settings_tab"):
            return self._vision.collect_settings_tab()
        return {}

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
