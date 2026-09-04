# -*- coding: utf-8 -*-
"""Плагин аватара: окно персонажа, если в его папке есть изображения."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from core.plugin_api import AppContext, Plugin, SettingField, HookResult

from plugins.avatar.window import AvatarWindow, has_avatar_images

_ANIM_RE = re.compile(r"\[ANIM:([a-zA-Z0-9_]+)\]", re.I)
_EMOTION_WORDS = {
    "happy": ("раду", "счаст", "😊", "👍"),
    "sad": ("груст", "жал", "😢"),
    "angry": ("зл", "бесит", "😠"),
    "surprised": ("удив", "wow", "😮"),
    "love": ("любл", "❤", "💕"),
    "sleepy": ("сплю", "спать", "😴"),
    "idle": (),
}


class PluginImpl(Plugin):
    id = "avatar"
    name = "Аватар персонажа"
    version = "1.0.0"
    description = "Окно с картинками из personas/characters/<id>/avatar|images|frames"
    settings_tab = "own"
    settings_tab_title = "Аватар"
    settings_schema = [
        SettingField("show", "Показывать окно аватара", "bool", True),
        SettingField("size", "Размер (px)", "int", 280, min_value=80, max_value=800),
        SettingField("always_on_top", "Поверх всех окон", "bool", True),
        SettingField(
            "corner",
            "Угол экрана",
            "choice",
            "bottom_right",
            choices=["bottom_right", "bottom_left", "top_right", "top_left"],
        ),
        SettingField("anim_ms", "Скорость анимации (мс)", "int", 80, min_value=30, max_value=500),
        SettingField("react_to_reply", "Менять кадр по ответу (ANIM/эмоции)", "bool", True),
    ]

    def __init__(self):
        self.win: Optional[AvatarWindow] = None
        self.app: Optional[AppContext] = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["avatar_plugin"] = self
        if not app.get_plugin_setting(self.id, "show", True):
            print("🖼 avatar: выключен в настройках", flush=True)
            return
        self._ensure_window()
        self._load_active()

    def on_shutdown(self, app: AppContext) -> None:
        if self.win is not None:
            try:
                self.win.close()
            except Exception:
                pass
            self.win = None

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self.app = app
        if not app.get_plugin_setting(self.id, "show", True):
            if self.win:
                self.win.hide()
            return
        self._ensure_window()
        self._load_active()

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        if not app.get_plugin_setting(self.id, "react_to_reply", True):
            return reply
        if not self.win or not self.win.isVisible():
            return reply
        name = None
        m = _ANIM_RE.search(reply or "")
        if m:
            name = m.group(1).lower()
            reply = _ANIM_RE.sub("", reply).strip()
        else:
            low = (reply or "").lower()
            for emo, keys in _EMOTION_WORDS.items():
                if any(k in low for k in keys) and self.win.has(emo):
                    name = emo
                    break
        if name:
            try:
                if self.win.has(name) and len(self.win._frames.get(name) or []) > 1:
                    self.win.play(name, loop=False)
                else:
                    self.win.show_static(name)
            except Exception as e:
                print(f"avatar anim: {e}", flush=True)
        return reply

    def _ensure_window(self) -> None:
        if self.win is None:
            self.win = AvatarWindow()
            # дать окну доступ к app для сохранения позиции при перемещении
            try:
                self.win.app = self.app
            except Exception:
                pass
        size = int(self.app.get_plugin_setting(self.id, "size", 280) or 280)
        self.win.set_display_size(size)
        self.win.set_always_on_top(
            bool(self.app.get_plugin_setting(self.id, "always_on_top", True))
        )
        self.win.set_anim_speed(
            int(self.app.get_plugin_setting(self.id, "anim_ms", 80) or 80)
        )

    def _load_active(self) -> None:
        if self.app is None or self.win is None:
            return
        cdir = self.app.get_character_dir()
        if not has_avatar_images(cdir):
            print(f"🖼 avatar: нет картинок в {cdir} — окно скрыто", flush=True)
            self.win.hide()
            return
        n = self.win.load_from_character_dir(cdir)
        print(f"🖼 avatar: {cdir.name} кадров/файлов≈{n} names={self.win.animation_names()[:12]}", flush=True)
        self.win.show_static("neutral")
        # Если задано явное положение (position) — использовать его, иначе переместить в угол
        pos = self.app.get_plugin_setting(self.id, "position", None)
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                x, y = int(pos[0]), int(pos[1])
                self.win.move(x, y)
            except Exception:
                corner = str(self.app.get_plugin_setting(self.id, "corner", "bottom_right") or "bottom_right")
                self.win.move_to_corner(corner)
        else:
            corner = str(self.app.get_plugin_setting(self.id, "corner", "bottom_right") or "bottom_right")
            self.win.move_to_corner(corner)
        if self.app.get_plugin_setting(self.id, "show", True):
            self.win.show()
