# -*- coding: utf-8 -*-
"""Автореакция на экран: SCENE_TO_ANIM + OCR + заголовок окна (порт screen_watch)."""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.plugin_api import AppContext, Plugin, SettingField

SCENE_TO_ANIM = {
    "cats": "happy",
    "cute": "happy_big",
    "meme": "giggling",
    "funny": "playful",
    "hentai": "flirty",
    "nsfw": "seductive",
    "porn": "seductive",
    "nude": "flirty",
    "code": "thinking",
    "terminal": "thinking",
    "error": "shocked",
    "comfy": "searching",
    "image_gen": "searching",
    "folder": "pointing",
    "files": "idle",
    "work": "idle",
    "docs": "thinking",
    "tax": "tired",
    "news_sad": "sad",
    "sad": "sad",
    "game": "playful",
    "video": "idle",
    "chat": "shy",
    "desktop": "idle",
    "empty": "sleepy",
    "steam": "happy",
    "youtube": "happy",
    "search": "searching",
}

TEXT_HINTS = [
    (re.compile(r"(?i)(comfy|генерац|нейросет)"), "searching"),
    (re.compile(r"(?i)(папк|проводн|explorer|файлов)"), "pointing"),
    (re.compile(r"(?i)(ошибк|traceback|exception|crash)"), "shocked"),
    (re.compile(r"(?i)(кот|кошк|puppy|мил|котик)"), "happy"),
    (re.compile(r"(?i)(hentai|хентай|18\+|nude|порн)"), "flirty"),
    (re.compile(r"(?i)(steam|игр[аыуе]|gameplay|bomba)"), "playful"),
    (re.compile(r"(?i)(youtube|ютуб|видео)"), "happy"),
    (re.compile(r"(?i)(груст|печал)"), "sad"),
    (re.compile(r"(?i)(vscode|visual studio|pycharm|code)"), "thinking"),
    (re.compile(r"(?i)(google|yandex|поиск)"), "searching"),
    (re.compile(r"(?i)(discord|telegram)"), "happy"),
]

ASK_SCREEN = (
    "на экране",
    "на моём экране",
    "на моем экране",
    "что видно",
    "скрин",
    "монитор",
    "посмотри экран",
    "что у меня на",
)


class PluginImpl(Plugin):
    id = "screen_react"
    name = "Реакция на экран"
    version = "1.1.0"
    description = "SCENE_TO_ANIM / OCR / заголовок → эмоция аватара"
    settings_tab = "own"
    settings_tab_title = "Реакция на экран"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("interval_seconds", "Интервал (сек)", "int", 20, min_value=5, max_value=600),
        SettingField("use_window_title", "Заголовок окна", "bool", True),
        SettingField("use_ocr_cache", "Читать OCR cache", "bool", True),
        SettingField("react_on_user_screen_question", "Реакция на «что на экране»", "bool", True),
        SettingField("chat_comments", "Комментарии в чат", "bool", False),
        SettingField("comment_chance_percent", "Шанс комментария %", "int", 15, min_value=0, max_value=100),
        SettingField("min_confidence", "Мин. уверенность", "float", 0.40, min_value=0.0, max_value=1.0),
        SettingField("hold_same_seconds", "Не дублировать (сек)", "int", 25, min_value=0, max_value=600),
        SettingField("debug_log", "Лог", "bool", True),
        SettingField("extra_rules", "Доп: слово=эмоция|...", "str", "bomba=surprised|котик=happy"),
    ]

    def __init__(self):
        self.app = None
        self._timer = None
        self._last_emotion = "neutral"
        self._last_at = 0.0
        self._last_sig = ""
        self._task = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["screen_react_plugin"] = self
        self._start_timer(app)
        print("👁 screen_react: loaded", flush=True)

    def on_shutdown(self, app: AppContext) -> None:
        if self._timer:
            try:
                self._timer.stop()
                self._timer.deleteLater()
            except Exception:
                pass
            self._timer = None

    def on_character_changed(self, character_id, previous_id, app):
        self.app = app
        self._restart_timer(app)

    def on_user_message(self, text, app):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        if not app.get_plugin_setting(self.id, "react_on_user_screen_question", True):
            return None
        low = (text or "").lower()
        if not any(p in low for p in ASK_SCREEN):
            return None
        ctx = self._collect(app)
        emotion, anim, conf = self._infer(app, ctx)
        if conf < 0.35:
            emotion, anim, conf = "searching", "searching", 0.7
        self._apply(app, emotion, anim, conf, "user_ask_screen", ctx)
        return None

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        """Если LLM вернул [SCENE:…] [ANIM:…] — применить."""
        if not reply:
            return reply
        m = re.search(r"\[SCENE:\s*([a-zA-Z0-9_]+)\]", reply, re.I)
        if m:
            scene = m.group(1).lower()
            anim = SCENE_TO_ANIM.get(scene)
            if anim:
                self._apply(app, scene, anim, 0.9, "scene_tag", {"signature": scene, "text": scene})
        m2 = re.search(r"\[ANIM:\s*([a-zA-Z0-9_]+)\]", reply, re.I)
        if m2 and not m:
            anim = m2.group(1).lower()
            self._apply(app, anim, anim, 0.85, "anim_tag", {"signature": anim, "text": anim})
        return reply

    def _start_timer(self, app):
        try:
            from PyQt5 import QtCore
        except ImportError:
            return
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(lambda: self._tick(app))
        self._restart_timer(app)

    def _restart_timer(self, app):
        if not self._timer:
            return
        sec = int(app.get_plugin_setting(self.id, "interval_seconds", 20) or 20)
        self._timer.start(max(5, sec) * 1000)

    def _tick(self, app):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        window = getattr(app, "window", None)
        if window is not None and getattr(window, "_busy", False):
            return
        try:
            ctx = self._collect(app)
            emotion, anim, conf = self._infer(app, ctx)
            min_c = float(app.get_plugin_setting(self.id, "min_confidence", 0.40) or 0.40)
            if conf < min_c:
                if app.get_plugin_setting(self.id, "debug_log", True):
                    print(f"screen_react: skip conf={conf:.2f}", flush=True)
                return
            hold = int(app.get_plugin_setting(self.id, "hold_same_seconds", 25) or 25)
            now = time.time()
            if emotion == self._last_emotion and now - self._last_at < hold and ctx.get("signature") == self._last_sig:
                return
            self._apply(app, emotion, anim, conf, "auto_screen", ctx)
        except Exception as e:
            print(f"screen_react tick: {e}", flush=True)

    def _collect(self, app) -> Dict[str, Any]:
        parts: List[str] = []
        title = ""
        if app.get_plugin_setting(self.id, "use_window_title", True):
            title = self._window_title()
            if title:
                parts.append(title)
        try:
            base = Path(getattr(app.config, "DATA_DIR", Path("data"))) / "cache"
            for name in ("screen_last.txt", "screen_last_ocr.txt"):
                p = base / name
                if p.is_file() and app.get_plugin_setting(self.id, "use_ocr_cache", True):
                    parts.append(p.read_text(encoding="utf-8", errors="ignore")[:800])
        except Exception:
            pass
        blob = " | ".join(parts)
        return {"title": title, "text": blob, "signature": re.sub(r"\s+", " ", blob.lower())[:180]}

    @staticmethod
    def _window_title() -> str:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return (buf.value or "").strip()
        except Exception:
            return ""

    def _infer(self, app, ctx) -> Tuple[str, str, float]:
        text = (ctx.get("text") or "").lower()
        if not text:
            return "neutral", "neutral", 0.0
        best_e, best_a, best_c = "neutral", "neutral", 0.0
        extra = str(app.get_plugin_setting(self.id, "extra_rules", "") or "")
        for chunk in extra.split("|"):
            if "=" not in chunk:
                continue
            word, emo = chunk.split("=", 1)
            word, emo = word.strip().lower(), emo.strip().lower()
            if word and word in text and 0.85 > best_c:
                best_e, best_a, best_c = emo, SCENE_TO_ANIM.get(emo, emo), 0.85
        for rx, anim in TEXT_HINTS:
            if rx.search(text):
                conf = 0.75
                if conf > best_c:
                    best_e, best_a, best_c = anim, anim, conf
        for scene, anim in SCENE_TO_ANIM.items():
            if scene in text:
                conf = 0.7
                if conf > best_c:
                    best_e, best_a, best_c = scene, anim, conf
        return best_e, best_a, best_c

    def _apply(self, app, emotion, anim, conf, source, ctx):
        self._last_emotion = emotion
        self._last_at = time.time()
        self._last_sig = ctx.get("signature") or ""
        app.state["screen_react_emotion"] = emotion
        app.state["screen_react_context"] = (ctx.get("text") or "")[:300]
        if app.get_plugin_setting(self.id, "debug_log", True):
            print(f"screen_react: {emotion}/{anim} conf={conf:.2f} ← {self._last_sig[:90]!r}", flush=True)
        emo = app.plugins.get("emotion") or app.state.get("emotion_plugin")
        if emo is not None and hasattr(emo, "set_context"):
            try:
                emo.set_context(app, emotion if emotion in SCENE_TO_ANIM or emotion in (
                    "happy", "sad", "thinking", "searching", "flirty", "playful", "shocked", "tired", "sleepy", "shy"
                ) else anim, source)
                if hasattr(emo, "_apply_avatar"):
                    app.state["emotion_animation"] = anim
                    emo.anim = anim
                    emo._apply_avatar(app, anim)
            except Exception as e:
                print(f"screen_react emotion: {e}", flush=True)
        else:
            av = app.plugins.get("avatar")
            if av is not None and hasattr(av, "apply_emotion"):
                try:
                    av.apply_emotion(anim)
                except Exception:
                    pass


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
