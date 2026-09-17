# -*- coding: utf-8 -*-
"""persona = эмоции + аватар. Все кадры из images/, не 24 штуки."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.plugin_api import AppContext, Plugin, SettingField

try:
    from plugins.persona.window import AvatarWindow, has_avatar_images
except Exception as _e:
    print(f"persona: window import FAIL: {_e}", flush=True)
    AvatarWindow = None

    def has_avatar_images(_p):
        return False

_ANIM_RE = re.compile(r"\[ANIM:([a-zA-Z0-9_]+)\]", re.I)

_FALLBACK = {
    "lust": "seductive",
    "horny": "seductive",
    "smile": "happy",
    "laugh": "giggling",
    "cry": "cry",
    "annoyed": "angry",
    "mad": "angry",
    "curious": "thinking",
    "wink": "teasing",
    "neutral": "idle",
    "hate": "angry",
}

_MOOD_HINT = {
    "happy": ("happy", "playful", "sly", "giggling"),
    "flirty": ("flirty", "love", "teasing", "seductive", "sly"),
    "sad": ("sad", "cry", "shy"),
    "angry": ("angry", "pouting", "frustrated"),
    "shy": ("shy", "blush", "embarrassed"),
    "curious": ("thinking", "searching", "surprised"),
    "calm": ("idle", "neutral"),
    "annoyed": ("angry", "pouting"),
}

_POSE_KEYS: List[Tuple[Tuple[str, ...], str]] = [
    (("танцуй", "потанцуй", "станцуй", "танец"), "dance"),
    (("хвостик", "хвост", "ушка", "уши"), "sly"),
    (("рук", "ладон", "пальц", "что держишь", "в руках"), "pointing"),
    (("укаж", "покажи сюда", "вот так", "посмотри сюда"), "pointing"),
    (("грудь", "сиськ", "тело ближе", "поближе", "крупнее", "крупный план"), "lingerie"),
    (("бель", "лифчик", "нижнее"), "lingerie"),
    (("раздень", "голая", "голую", "ню ", "без одежд"), "undress"),
    (("ванн", "моешь", "купа"), "bath"),
    (("кроват", "ляж", "ложись", "в постель"), "bed"),
    (("подмигн", "дразн"), "teasing"),
    (("смущ", "стесня"), "shy"),
    (("любл", "поцел", "обним"), "love"),
    (("ревн",), "jealous"),
    (("бесит", "злюсь", "злая"), "angry"),
    (("груст", "плач"), "cry"),
    (("устал", "спать", "спи "), "sleepy"),
    (("боле", "плохо себя"), "sick"),
    (("удиви", "ого", "шок"), "shocked"),
    (("испуг", "страшн"), "scared"),
    (("горж", "молодец"), "proud"),
    (("балу", "дуроч"), "mischievous"),
    (("подумай", "думай"), "thinking"),
    (("поиск",), "searching"),
    (("хихи", "хаха"), "giggling"),
    (("покажи себя", "как ты выглядишь"), "idle"),
]

_INTENT_ANIM = {
    "web_search": "searching",
    "search_similar": "searching",
    "imggen": "pointing",
    "imggen_edit": "thinking",
    "describe_screen": "searching",
    "deep_think": "thinking",
    "pc_open": "pointing",
    "pc_search_files": "searching",
    "memory_add": "happy",
    "reminder_add": "surprised",
}


class PluginImpl(Plugin):
    id = "persona"
    name = "Персона (эмоции + аватар)"
    version = "1.1.0"
    description = "Настроение, все кадры, [ANIM:], окно спрайтов"
    settings_tab = "own"
    settings_tab_title = "Персона"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("show_avatar", "Показывать окно аватара", "bool", True),
        SettingField("inject_mood", "Писать настроение и кадры в system", "bool", True),
        SettingField("react_to_reply", "Менять кадр по ответу / [ANIM:]", "bool", True),
        SettingField("anim_ms", "Скорость анимации (мс)", "int", 80, min_value=30, max_value=500),
    ]

    def __init__(self):
        self.win = None
        self.app = None
        self._keywords: List[dict] = []
        self._forbidden: set = set()
        self._forbid_fallback = "pouting"
        self._nsfw = True

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state.setdefault("emotion", "idle")
        app.state.setdefault("emotion_animation", "idle")
        app.state["avatar_plugin"] = self
        app.state["emotion_plugin"] = self
        print("🎭 persona 1.1: all sprites + mood", flush=True)
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
        if source == "companion_mood":
            return
        if app.get_plugin_setting(self.id, "show_avatar", True):
            self.apply_emotion(emotion)

    def set_animation(self, name: str, app=None) -> None:
        self.apply_emotion(name)

    def on_user_message(self, text, app):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        low = (text or "").lower()
        hit = self._match_pose(low)
        if hit:
            app.state["persona_pose_request"] = hit
            app.state["emotion"] = hit.split("_")[0]
            app.state["emotion_animation"] = hit
            app.state["emotion_source"] = "user_pose"
            if app.get_plugin_setting(self.id, "show_avatar", True):
                self.apply_emotion(hit)
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not app.get_plugin_setting(self.id, "inject_mood", True):
            return messages
        mood = str(app.state.get("companion_mood") or app.state.get("emotion") or "idle")
        anim = str(app.state.get("emotion_animation") or mood)
        names = self._live_names()
        grouped = ", ".join(names)
        pose = str(app.state.get("persona_pose_request") or "")
        extra = f" Кадры (ставь ОДНО [ANIM:точное_имя] в конце): {grouped}."
        pose_line = f" Пользователь просит позу «{pose}» — ответь в ней и поставь [ANIM:{pose}]." if pose else ""
        block = (
            f"\n\n[НАСТРОЕНИЕ] {mood}, кадр сейчас {anim}.{extra}{pose_line}\n"
            "Меняй кадр каждый ответ. Не только idle. "
            "Поза/тело: pointing=руки/указать, sly/teasing=хвост/уши, "
            "lingerie/undress=тело ближе, dance=танец, bed=кровать, bath=ванна, "
            "proud/confident=гордость, jealous=ревность, giggling=смех.\n"
        )
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + block
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return reply
        tags = _ANIM_RE.findall(reply or "")
        name = tags[-1].lower().strip() if tags else ""
        if name:
            app.state["emotion_animation"] = name
            app.state["emotion"] = name.split("_")[0]
            print(f"persona [ANIM:] → {name}", flush=True)
        if not name:
            name = str(app.state.get("persona_pose_request") or "") or self._auto_frame(app)
        app.state["persona_pose_request"] = ""
        if name and app.get_plugin_setting(self.id, "react_to_reply", True):
            self.apply_emotion(name)
        cleaned = _ANIM_RE.sub("", reply or "")
        return cleaned.strip("\n")

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
        name = self._resolve(str(emotion or "idle").lower().strip())
        if not name:
            print(f"persona: нет кадра {emotion}", flush=True)
            return
        frames = self.win._frames.get(name) or []
        print(f"persona: frame {name} n={len(frames)}", flush=True)
        if len(frames) > 1:
            self.win.play(name, loop=True)
        else:
            self.win.show_static(name)

    def _live_names(self) -> List[str]:
        if self.win and hasattr(self.win, "animation_names"):
            return [n for n in self.win.animation_names() if n not in self._forbidden]
        return []

    def _resolve(self, raw: str) -> str:
        raw = (raw or "idle").lower().strip()
        names = set(self._live_names())
        if not names and self.win:
            names = set(self.win.animation_names())
        mood = str((self.app.state.get("companion_mood") if self.app else "") or "")
        candidates = []
        if mood:
            for suf in _MOOD_HINT.get(mood, (mood,)):
                candidates.append(f"{raw}_{suf}")
                candidates.append(f"{suf}_{raw}")
        candidates.append(raw)
        if raw in _FALLBACK:
            candidates.append(_FALLBACK[raw])
        candidates.extend([raw.split("_")[0], "idle", "neutral", "happy"])
        for c in candidates:
            if c in self._forbidden:
                if self._forbid_fallback in names:
                    return self._forbid_fallback
                continue
            if c in names:
                return c
        for alt in list(names):
            if alt == raw or alt.startswith(raw + "_") or raw.startswith(alt + "_"):
                if alt not in self._forbidden:
                    return alt
        return self._forbid_fallback if self._forbid_fallback in names else (next(iter(names), ""))

    def _match_pose(self, low: str) -> str:
        for item in self._keywords:
            keys = item.get("keys") or []
            anim = str(item.get("anim") or "")
            if anim and any(k in low for k in keys):
                return self._resolve(anim) or anim
        for keys, anim in _POSE_KEYS:
            if any(k in low for k in keys):
                if not self._nsfw and anim in ("undress", "lingerie", "bath", "bed", "naked", "seductive"):
                    return self._resolve(self._forbid_fallback)
                return self._resolve(anim) or anim
        return ""

    def _auto_frame(self, app: AppContext) -> str:
        intent = str(app.state.get("last_intent") or "")
        if intent in _INTENT_ANIM:
            return _INTENT_ANIM[intent]
        mood = str(app.state.get("companion_mood") or app.state.get("emotion") or "idle")
        hints = _MOOD_HINT.get(mood, (mood, "idle"))
        names = set(self._live_names())
        idle_var = f"idle_{mood}" if mood in ("happy", "sad", "angry", "sly") else ""
        pool = [h for h in ((idle_var,) + hints) if h and h in names]
        if not pool:
            pool = [h for h in hints if h in names]
        if not pool:
            return "idle"
        last = str(app.state.get("emotion_animation") or "")
        if last in pool and len(pool) > 1:
            pool = [p for p in pool if p != last]
        return random.choice(pool)

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
        self._load_maps()
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
        print(f"persona: {cdir.name} files≈{n} unique={len(names)}", flush=True)
        start = "idle" if self.win.has("idle") else ("neutral" if self.win.has("neutral") else (names[0] if names else "idle"))
        self.win.show_static(start)
        self.win.show()

    def _load_maps(self) -> None:
        self._keywords = []
        self._forbidden = set()
        self._forbid_fallback = "pouting"
        self._nsfw = True
        if self.app is None:
            return
        cdir = self.app.get_character_dir()
        for fname in ("emotions_map.json", "reactions.json"):
            p = Path(cdir) / fname
            if not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"persona: {fname} {e}", flush=True)
                continue
            for row in data.get("keywords") or []:
                if isinstance(row, dict):
                    self._keywords.append(row)
            for row in data.get("reactions") or []:
                if not isinstance(row, dict):
                    continue
                phrases = row.get("phrases") or []
                sprite = row.get("sprite") or row.get("anim") or ""
                if phrases and sprite:
                    self._keywords.append({"keys": phrases, "anim": sprite})
        try:
            from character_catalog import read_character_card
            card = read_character_card(str(self.app.get_active_character() or "")) or ""
        except Exception:
            card = ""
        self._nsfw = True
        for raw in (card or "").splitlines()[:20]:
            line = raw.strip().lower()
            if line.startswith("nsfw:"):
                self._nsfw = line.split(":", 1)[-1].strip() in ("true", "yes", "1", "on", "да")
                break
        grab = False
        for line in (card or "").splitlines():
            s = line.strip()
            low = s.lower()
            if low.startswith("## анимации запрещен"):
                grab = True
                continue
            if low.startswith("## "):
                grab = False
            if grab and s and not s.startswith("#"):
                for part in s.replace(";", ",").split(","):
                    n = part.strip().lower()
                    if n:
                        self._forbidden.add(n)
        nxt = False
        for line in (card or "").splitlines():
            s = line.strip()
            if s.lower().startswith("## анимация вместо"):
                nxt = True
                continue
            if nxt and s and not s.startswith("#"):
                self._forbid_fallback = s.split()[0].strip(",.").lower()
                break


def register():
    return PluginImpl()
