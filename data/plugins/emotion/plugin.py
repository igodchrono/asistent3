# -*- coding: utf-8 -*-
"""Эмоции: полный EmotionalAnalyzer (asistent2) + кадры аватара + map."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

DEFAULT_EMOTION_ANIM = {
    "love": "love_warm",
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "hate": "angry",
    "fear": "scared",
    "flirty": "flirty",
    "undress": "undress",
    "thinking": "thinking",
    "surprised": "surprised",
    "sleepy": "sleepy",
    "tired": "tired",
    "searching": "searching",
    "playful": "playful",
    "shy": "shy",
    "dance": "dance",
    "neutral": "neutral",
}

HOLD_SECONDS = {
    "love": 120,
    "sad": 90,
    "angry": 60,
    "hate": 60,
    "flirty": 75,
    "undress": 50,
    "happy": 45,
    "thinking": 25,
    "searching": 25,
    "neutral": 5,
}

MOOD_INSTRUCTIONS = {
    "sad": "Пользователь грустит. Отвечай мягко.",
    "angry": "Пользователь раздражён. Коротко и по делу.",
    "love": "Нежный тон.",
    "happy": "Живее обычного.",
    "flirty": "Лёгкий флирт в рамках характера.",
    "thinking": "Вдумчивый ответ.",
}


class PluginImpl(Plugin):
    id = "emotion"
    name = "Эмоции"
    version = "3.0.0"
    description = "EmotionalAnalyzer из asistent2 + кадры + emotions_map.json"
    settings_tab = "own"
    settings_tab_title = "Эмоции"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("confidence_threshold", "Мин. уверенность", "float", 0.25, min_value=0.0, max_value=1.0),
        SettingField("hold_seconds", "Мин. hold (сек)", "int", 8, min_value=0, max_value=3600),
        SettingField("add_mood_to_prompt", "Эмоция в промпт", "bool", True),
        SettingField("apply_before_llm", "Менять аватар сразу", "bool", True),
        SettingField("force_change_on_any_message", "Менять почти на каждое сообщение", "bool", True),
        SettingField("use_full_analyzer", "Полный emotion_analyzer", "bool", True),
        SettingField("debug_log", "Лог в консоль", "bool", False),
    ]

    def __init__(self):
        self.app: Optional[AppContext] = None
        self.emotion = "neutral"
        self.anim = "neutral"
        self.confidence = 0.0
        self.until = 0.0
        self._analyzer = None
        self._analyzer_failed = False
        self._map_cache: Dict[str, Any] = {}
        self._map_mtime = 0.0

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["emotion_plugin"] = self
        if app.get_plugin_setting(self.id, "use_full_analyzer", True):
            self._get_analyzer(app)

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self.app = app
        self.emotion = "neutral"
        self.anim = "neutral"
        self.confidence = 0.0
        self.until = 0.0
        self._map_cache = {}
        app.state["emotion"] = "neutral"
        app.state["emotion_animation"] = "neutral"
        app.state["emotion_from_plugin"] = False
        # analyzer memory per character
        self._analyzer = None
        self._analyzer_failed = False

    def set_context(self, app: AppContext, emotion: str, source: str = "") -> None:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        emotion = self._normalize(emotion)
        anim = self._pick_anim(app, emotion)
        self.emotion = emotion
        self.anim = anim
        self.confidence = 1.0
        self.until = time.time() + float(HOLD_SECONDS.get(emotion, 40))
        app.state["emotion"] = emotion
        app.state["emotion_animation"] = anim
        app.state["emotion_source"] = source
        app.state["emotion_from_plugin"] = True
        self._apply_avatar(app, anim)

    def on_user_message(self, text: str, app: AppContext):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        snap = self._observe(app, text or "")
        app.state["emotion"] = snap["emotion"]
        app.state["emotion_animation"] = snap["anim"]
        app.state["emotion_confidence"] = snap["confidence"]
        app.state["emotion_from_plugin"] = True
        if app.get_plugin_setting(self.id, "force_change_on_any_message", True) or snap["emotion"] != "neutral":
            self._apply_avatar(app, snap["anim"])
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        text = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                c = m.get("content")
                text = c if isinstance(c, str) else ""
                break
        snap = self._observe(app, text)
        app.state["emotion"] = snap["emotion"]
        app.state["emotion_animation"] = snap["anim"]
        app.state["emotion_from_plugin"] = True
        if app.get_plugin_setting(self.id, "apply_before_llm", True):
            self._apply_avatar(app, snap["anim"])
        if app.get_plugin_setting(self.id, "add_mood_to_prompt", True) and snap["emotion"] != "neutral":
            instr = MOOD_INSTRUCTIONS.get(snap["emotion"])
            if instr and messages and messages[0].get("role") == "system":
                messages[0]["content"] = str(messages[0].get("content") or "") + "\n\nЭмоциональный контекст:\n- " + instr
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return reply
        self._apply_avatar(app, self.anim)
        return reply

    def _observe(self, app: AppContext, text: str) -> Dict[str, Any]:
        now = time.time()
        result = self._analyze(app, text)
        emotion = self._normalize(result.get("emotion"))
        confidence = float(result.get("confidence") or 0.0)
        anim = result.get("anim") or self._pick_anim(app, emotion)
        threshold = float(app.get_plugin_setting(self.id, "confidence_threshold", 0.25) or 0.25)
        force = bool(app.get_plugin_setting(self.id, "force_change_on_any_message", True))

        if now < self.until and self.emotion != "neutral" and not force:
            if emotion == "neutral" or confidence < threshold:
                if not (confidence >= 0.55 and emotion not in ("neutral", self.emotion)):
                    return {"emotion": self.emotion, "anim": self.anim, "confidence": self.confidence}

        if confidence >= threshold or emotion != "neutral" or now >= self.until:
            self.emotion = emotion
            self.anim = anim
            self.confidence = confidence
            minimum = int(app.get_plugin_setting(self.id, "hold_seconds", 8) or 8)
            self.until = now + max(float(minimum), float(HOLD_SECONDS.get(emotion, 40)))
        return {"emotion": self.emotion, "anim": self.anim, "confidence": self.confidence}

    def _analyze(self, app: AppContext, text: str) -> Dict[str, Any]:
        # map keywords first
        hit = self._match_map_keywords(app, text)
        if hit:
            return hit
        analyzer = self._get_analyzer(app)
        if analyzer is not None:
            try:
                if hasattr(analyzer, "analyze_emotion"):
                    r = analyzer.analyze_emotion(text) or {}
                    emotion = self._normalize(r.get("dominant"))
                    conf = float(r.get("confidence") or 0.0)
                    anim = r.get("anim") or self._pick_anim(app, emotion)
                    if emotion != "neutral":
                        return {"emotion": emotion, "anim": anim, "confidence": conf, "source": "analyzer"}
                elif hasattr(analyzer, "analyze_full_context"):
                    emotion, details = analyzer.analyze_full_context(text or "")
                    emotion = self._normalize(emotion)
                    scores = (details or {}).get("scores") or {}
                    conf = float(max(scores.values()) if scores else 0.6)
                    if conf > 1:
                        conf = min(1.0, conf / 5.0)
                    return {
                        "emotion": emotion,
                        "anim": self._pick_anim(app, emotion),
                        "confidence": conf,
                        "source": "analyzer",
                    }
            except Exception as e:
                if app.get_plugin_setting(self.id, "debug_log", False):
                    print(f"emotion analyzer: {e}", flush=True)
        # hybrid fallback
        try:
            from models.intent_model.micro_models import HybridAnalyzer

            ha = HybridAnalyzer(use_micro_models=True)
            r = ha.analyze_emotion(text) or {}
            emotion = self._normalize(r.get("dominant"))
            conf = float(r.get("confidence") or 0.0)
            return {
                "emotion": emotion,
                "anim": self._pick_anim(app, emotion),
                "confidence": conf,
                "source": "hybrid",
            }
        except Exception:
            pass
        return {"emotion": "neutral", "anim": "neutral", "confidence": 0.0}

    def _get_analyzer(self, app: Optional[AppContext] = None):
        if self._analyzer is not None or self._analyzer_failed:
            return self._analyzer
        try:
            from emotion_analyzer import EmotionalAnalyzer

            mem = "emotional_memory.json"
            if app is not None:
                try:
                    mem = str(app.get_character_dir() / "emotional_memory.json")
                except Exception:
                    pass
            self._analyzer = EmotionalAnalyzer(memory_file=mem)
            print("🧠 emotion: EmotionalAnalyzer loaded", flush=True)
        except Exception as e:
            self._analyzer_failed = True
            print(f"emotion: EmotionalAnalyzer unavailable: {e}", flush=True)
        return self._analyzer

    def _match_map_keywords(self, app: AppContext, text: str) -> Optional[Dict[str, Any]]:
        low = (text or "").lower()
        data = self._load_map(app)
        for item in data.get("keywords") or []:
            keys = item.get("keys") or []
            if any(str(k).lower() in low for k in keys):
                emotion = self._normalize(item.get("emotion") or "neutral")
                anim = str(item.get("anim") or DEFAULT_EMOTION_ANIM.get(emotion, emotion))
                anim = self._resolve(app, anim, emotion)
                return {
                    "emotion": emotion,
                    "anim": anim,
                    "confidence": float(item.get("confidence") or 0.92),
                    "source": "map",
                }
        return None

    def _load_map(self, app: AppContext) -> Dict[str, Any]:
        try:
            path = app.get_character_dir() / "emotions_map.json"
            if not path.is_file():
                return {}
            mtime = path.stat().st_mtime
            if self._map_cache and mtime == self._map_mtime:
                return self._map_cache
            data = json.loads(path.read_text(encoding="utf-8"))
            self._map_cache = data if isinstance(data, dict) else {}
            self._map_mtime = mtime
            return self._map_cache
        except Exception:
            return {}

    def _pick_anim(self, app: AppContext, emotion: str) -> str:
        data = self._load_map(app)
        mapped = (data.get("emotions") or {}).get(emotion)
        preferred = mapped or DEFAULT_EMOTION_ANIM.get(emotion, emotion)
        return self._resolve(app, preferred, emotion)

    def _available(self, app: AppContext) -> List[str]:
        avatar = app.plugins.get("avatar")
        win = getattr(avatar, "win", None) if avatar else None
        if win is not None and hasattr(win, "animation_names"):
            try:
                return list(win.animation_names() or [])
            except Exception:
                pass
        return list(DEFAULT_EMOTION_ANIM.values())

    def _resolve(self, app: AppContext, preferred: str, emotion: str) -> str:
        names = self._available(app)
        s = set(names)
        for cand in (preferred, emotion, DEFAULT_EMOTION_ANIM.get(emotion, ""), "neutral", "idle"):
            c = (cand or "").lower()
            if c in s:
                return c
            for n in names:
                if n.startswith(c + "_") or c.startswith(n):
                    return n
        return names[0] if names else "neutral"

    def _apply_avatar(self, app: AppContext, anim: Optional[str] = None) -> None:
        name = str(anim or self.anim or "neutral")
        name = self._resolve(app, name, self.emotion)
        if app.get_plugin_setting(self.id, "debug_log", False):
            print(f"emotion → anim={name} emotion={self.emotion} conf={self.confidence:.2f}", flush=True)
        avatar = app.plugins.get("avatar")
        if avatar is not None and hasattr(avatar, "apply_emotion"):
            try:
                avatar.apply_emotion(name)
            except Exception as e:
                print(f"emotion avatar: {e}", flush=True)

    @staticmethod
    def _normalize(value: Any) -> str:
        aliases = {
            "joy": "happy",
            "sadness": "sad",
            "anger": "angry",
            "rage": "angry",
            "surprise": "surprised",
            "sexy": "flirty",
            "nude": "undress",
            "naked": "undress",
            "sleep": "sleepy",
        }
        e = str(value or "neutral").strip().lower()
        return aliases.get(e, e)


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
