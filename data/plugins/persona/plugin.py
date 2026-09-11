# -*- coding: utf-8 -*-
"""persona = emotion + avatar в одном плагине."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

try:
    from plugins.persona.window import AvatarWindow, has_avatar_images
except Exception as _e:
    print(f"persona: window import FAIL: {_e}", flush=True)
    try:
        from plugins.avatar.window import AvatarWindow, has_avatar_images
        print("persona: fallback plugins.avatar.window", flush=True)
    except Exception as _e2:
        print(f"persona: avatar.window тоже нет: {_e2}", flush=True)
        AvatarWindow = None
        def has_avatar_images(_p):
            return False

_ANIM_RE = re.compile(r"\[ANIM:([a-zA-Z0-9_]+)\]", re.I)
_EMOTION_WORDS = {
    "happy": ("раду", "счаст", "ура", "супер", "класс", "😊", "👍"),
    "sad": ("груст", "жал", "печал", "скуч", "😢"),
    "angry": ("зл", "бесит", "раздраж", "😠"),
    "surprised": ("удив", "wow", "😮"),
    "love": ("любл", "❤", "💕"),
    "shy": ("смущ", "стесня"),
    "sleepy": ("сплю", "спать", "😴"),
}
_ALIASES = {
    "playful": "happy", "flirty": "blush", "lust": "love", "horny": "love",
    "smile": "happy", "laugh": "happy", "cry": "sad", "annoyed": "angry",
    "mad": "angry", "curious": "thinking", "searching": "thinking",
    "pointing": "confident", "wink": "happy", "neutral": "idle",
    "smirking": "confident",
}


class PluginImpl(Plugin):
    id = "persona"
    name = "Персона (эмоции + аватар)"
    version = "1.0.0"
    description = "Настроение, [ANIM:], окно спрайтов — один контур"
    settings_tab = "own"
    settings_tab_title = "Персона"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("show_avatar", "Показывать окно аватара", "bool", True),
        SettingField("inject_mood", "Писать настроение в system", "bool", True),
        SettingField("react_to_reply", "Менять кадр по ответу / [ANIM:]", "bool", True),
        SettingField("anim_ms", "Скорость анимации (мс)", "int", 80, min_value=30, max_value=500),
    ]

    def __init__(self):
        self.win = None
        self.app = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state.setdefault("emotion", "neutral")
        app.state.setdefault("emotion_animation", "idle")
        app.state["avatar_plugin"] = self
        app.state["emotion_plugin"] = self
        # чтобы старые вызовы app.plugins.get("avatar"|"emotion") находили нас
        app.plugins["avatar"] = self
        app.plugins["emotion"] = self
        print("🎭 persona 1.0: emotion+avatar", flush=True)
        if app.get_plugin_setting(self.id, "show_avatar", True):
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
        if not app.get_plugin_setting(self.id, "show_avatar", True):
            if self.win:
                self.win.hide()
            return
        self._ensure_window()
        self._load_active()

    def set_context(self, app: AppContext, emotion: str, source: str = "") -> None:
        app.state["emotion"] = emotion
        app.state["emotion_animation"] = emotion
        app.state["emotion_source"] = source
        if app.get_plugin_setting(self.id, "show_avatar", True):
            self.apply_emotion(emotion)

    def set_animation(self, name: str, app=None) -> None:
        self.apply_emotion(name)

    def on_user_message(self, text, app):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        low = (text or "").lower()
        for emo, keys in _EMOTION_WORDS.items():
            if keys and any(k in low for k in keys):
                self.set_context(app, emo, "user_text")
                break
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not app.get_plugin_setting(self.id, "inject_mood", True):
            return messages
        mood = str(app.state.get("emotion") or "neutral")
        anim = str(app.state.get("emotion_animation") or mood)
        names = []
        if self.win and hasattr(self.win, "animation_names"):
            names = self.win.animation_names()[:24]
        extra = f" Доступные спрайты: {', '.join(names)}." if names else ""
        block = (
            f"\n\n[ЭМОЦИЯ] сейчас {mood}, анимация {anim}.{extra} "
            f"В конце ответа можно [ANIM:имя_спрайта].\n"
        )
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return reply
        m = _ANIM_RE.search(reply or "")
        name = m.group(1).lower().strip() if m else ""
        if name:
            app.state["emotion_animation"] = name
            app.state["emotion"] = name.split("_")[0]
            print(f"persona [ANIM:] → {name}", flush=True)
        if not name:
            name = str(app.state.get("emotion_animation") or app.state.get("emotion") or "").lower()
            if name in ("", "neutral", "none"):
                name = ""
        if name and app.get_plugin_setting(self.id, "react_to_reply", True):
            self.apply_emotion(name)
        return reply

    def apply_emotion(self, emotion: str) -> None:
        if self.app is None:
            return
        if not self.app.get_plugin_setting(self.id, "show_avatar", True):
            return
        self._ensure_window()
        if self.win is None:
            return
        if not getattr(self.win, "_frames", None):
            self._load_active()
        try:
            if not self.win.isVisible():
                self.win.show()
        except Exception:
            pass
        raw = str(emotion or "idle").lower().strip()
        name = _ALIASES.get(raw, raw)
        if not self.win.has(name):
            picked = None
            for alt in list(self.win.animation_names()):
                if alt == name or alt.startswith(name + "_") or name.startswith(alt + "_"):
                    picked = alt
                    break
            if not picked:
                for alt in (name.split("_")[0], "idle", "neutral", "happy"):
                    if self.win.has(alt):
                        picked = alt
                        break
            if not picked:
                print(f"persona: нет кадра {raw}/{name}", flush=True)
                return
            name = picked
        frames = self.win._frames.get(name) or []
        print(f"persona: frame {name} n={len(frames)}", flush=True)
        if len(frames) > 1:
            self.win.play(name, loop=True)
        else:
            self.win.show_static(name)

    def _ensure_window(self) -> None:
        if AvatarWindow is None:
            print("persona: AvatarWindow is None — положи plugins/persona/window.py", flush=True)
            return
        if self.win is None:
            self.win = AvatarWindow()
            try:
                self.win.app = self.app
            except Exception:
                pass
        if self.app is None:
            return
        self.win.set_anim_speed(int(self.app.get_plugin_setting(self.id, "anim_ms", 80) or 80))

    def _load_active(self) -> None:
        if self.app is None or self.win is None:
            return
        cdir = self.app.get_character_dir()
        if not has_avatar_images(cdir):
            print(f"persona: нет картинок в {cdir}", flush=True)
            try:
                self.win.hide()
            except Exception:
                pass
            return
        n = self.win.load_from_character_dir(cdir)
        names = self.win.animation_names()
        print(f"persona: {cdir.name} frames≈{n} names={names[:12]} total={len(names)}", flush=True)
        self.win.show_static("idle" if self.win.has("idle") else ("neutral" if self.win.has("neutral") else (names[0] if names else "idle")))
        self.win.show()


def register():
    return PluginImpl()
