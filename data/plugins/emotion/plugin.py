# -*- coding: utf-8 -*-
"""Плагин распознавания эмоций пользователя и управления эмоцией аватара."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

EMOTION_TO_ANIM = {
    "love": "love_warm", "love_shy": "love_shy", "happy": "happy", "joy": "happy_big",
    "sad": "sad", "cry": "cry", "angry": "angry", "hate": "angry",
    "disgust": "angry_frustrated", "fear": "scared",
    "frustrated": "angry_frustrated", "flirty": "flirty", "teasing": "teasing",
    "seductive": "seductive", "undress": "undress", "thinking": "thinking",
    "surprised": "surprised", "sleepy": "sleepy", "tired": "tired",
    "searching": "searching", "local_search": "searching", "working": "thinking",
    "playful": "playful", "shy": "shy", "proud": "proud", "neutral": "neutral",
}

OPERATION_COMMENTS = {
    "searching": "Сейчас посмотрю, что найдётся в интернете.",
    "local_search": "Сейчас поищу это среди файлов на компьютере.",
    "thinking": "Секунду, выполняю эту операцию на компьютере.",
    "happy": "О, интересный запрос — посмотрю с удовольствием.",
    "flirty": "О, запрос с перчинкой. Сейчас посмотрю, что найдётся.",
    "sad": "Понимаю настроение. Постараюсь найти полезную информацию.",
    "angry": "Поняла. Проверю информацию внимательнее.",
    "surprised": "Интересный поворот. Сейчас проверю, что удалось найти.",
    "fear": "Проверю информацию осторожно и покажу результаты.",
}

HOLD_SECONDS = {
    "love": 900, "sad": 720, "cry": 720, "angry": 480, "hate": 480,
    "tired": 600, "sleepy": 600, "flirty": 420, "undress": 360,
    "happy": 300, "surprised": 90, "thinking": 60, "searching": 60, "local_search": 60, "neutral": 20,
}

MOOD_INSTRUCTIONS = {
    "sad": "Пользователь грустит. Отвечивай мягко, без фразы «улыбнись» и без лекций.",
    "cry": "Пользователь расстроен. Ответь коротко и тепло, без большого списка советов.",
    "angry": "Пользователь раздражён. Отвечай коротко и по делу, без спора и слащавости.",
    "hate": "Пользователь зол. Сохраняй спокойный тон, без подколок.",
    "tired": "Пользователь устал. Отвечай короче обычного, без лишних списков.",
    "sleepy": "Пользователь сонный. Отвечай тихо и коротко.",
    "love": "Пользователь настроен нежно. Отвечай теплее, сохраняя характер персонажа.",
    "happy": "У пользователя хорошее настроение. Отвечай живее, без капса и чрезмерности.",
    "surprised": "Пользователь удивлён. Сначала коротко раздели удивление, затем переходи к делу.",
    "playful": "Пользователь настроен игриво. Допустима лёгкая доброжелательная подколка.",
}


class PluginImpl(Plugin):
    id = "emotion"
    name = "Эмоции"
    version = "2.0.0"
    description = "Распознаёт эмоцию пользователя через базовую модель и меняет анимацию аватара."
    settings_tab = "own"
    settings_tab_title = "Эмоции"
    settings_schema = [
        SettingField("enabled", "Включить распознавание эмоций", "bool", True),
        SettingField("confidence_threshold", "Минимальная уверенность", "float", 0.4, min_value=0.0, max_value=1.0),
        SettingField("hold_seconds", "Минимальная длительность эмоции (сек.)", "int", 20, min_value=0, max_value=3600),
        SettingField("add_mood_to_prompt", "Учитывать эмоцию в ответе ассистента", "bool", True),
    ]
    def __init__(self):
        self.app: Optional[AppContext] = None
        self.emotion = "neutral"
        self.anim = "neutral"
        self.confidence = 0.0
        self.until = 0.0
        self._analyzer = None
        self._analyzer_failed = False

    def set_context(self, app: AppContext, emotion: str, source: str = "") -> None:
        """Применить состояние от плагина, который выполняет операцию ПК или поиска."""
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        self.app = app
        emotion = self._normalize(emotion)
        self.emotion = emotion
        self.anim = EMOTION_TO_ANIM.get(emotion, emotion)
        self.confidence = 1.0
        self.until = time.time() + float(HOLD_SECONDS.get(emotion, 60))
        app.state["emotion"] = emotion
        app.state["emotion_animation"] = self.anim
        app.state["emotion_source"] = source
        self._apply_avatar(app)

    def apply_operation(self, app: AppContext, fallback_emotion: str, text: str = "", source: str = "") -> str:
        """Определить эмоцию по запросу операции и вернуть комментарий для чата."""
        if not app.get_plugin_setting(self.id, "enabled", True):
            return ""
        result = self._analyze(text) if text else {"emotion": "neutral", "confidence": 0.0}
        threshold = float(app.get_plugin_setting(self.id, "confidence_threshold", 0.4) or 0.4)
        emotion = self._normalize(result.get("emotion"))
        confidence = float(result.get("confidence") or 0.0)
        if emotion == "neutral" or confidence < threshold:
            emotion = fallback_emotion
        self.set_context(app, emotion, source)
        return self.operation_comment(emotion, fallback_emotion)

    @staticmethod
    def operation_comment(emotion: str, fallback: str = "thinking") -> str:
        return OPERATION_COMMENTS.get(emotion, OPERATION_COMMENTS.get(fallback, "Готово."))

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["emotion_plugin"] = self

    def on_shutdown(self, app: AppContext) -> None:
        self._analyzer = None

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self.app = app
        self.emotion = "neutral"
        self.anim = "neutral"
        self.confidence = 0.0
        self.until = 0.0

    def _get_analyzer(self):
        if self._analyzer is not None or self._analyzer_failed:
            return self._analyzer
        try:
            from models.intent_model.micro_models import HybridAnalyzer
            self._analyzer = HybridAnalyzer(use_micro_models=True)
        except Exception as exc:
            self._analyzer_failed = True
            print(f"emotion: analyzer unavailable: {exc}", flush=True)
        return self._analyzer

    def _analyze(self, text: str) -> Dict[str, Any]:
        rule_result = self._analyze_rules(text)
        if rule_result["emotion"] != "neutral":
            return rule_result
        analyzer = self._get_analyzer()
        if analyzer is not None:
            try:
                result = analyzer.analyze_emotion(text) or {}
                emotion = self._normalize(result.get("dominant"))
                confidence = float(result.get("confidence") or 0.0)
                return {"emotion": emotion, "anim": EMOTION_TO_ANIM.get(emotion, emotion),
                        "confidence": confidence, "source": result.get("source", "hybrid")}
            except Exception as exc:
                print(f"emotion: analyze failed: {exc}", flush=True)
        return self._analyze_rules(text)

    @staticmethod
    def _normalize(value: Any) -> str:
        aliases = {"joy": "happy", "happiness": "happy", "sadness": "sad", "anger": "angry",
                   "rage": "angry", "disgust": "disgust", "fear": "fear",
                   "surprise": "surprised", "sexy": "flirty", "nude": "undress",
                   "naked": "undress", "sleep": "sleepy", "fatigue": "tired"}
        emotion = str(value or "neutral").strip().lower()
        return aliases.get(emotion, emotion)

    def _analyze_rules(self, text: str) -> Dict[str, Any]:
        low = (text or "").lower()
        rules = ((("люблю тебя", "обожаю тебя", "i love you", "❤️", "💕"), "love", 0.85),
                 (("ура", "отлично", "класс", "супер", "радост", "весело"), "happy", 0.8),
                 (("грустно", "плохо мне", "плачу", "тоска"), "sad", 0.8),
                 (("бесит", "злой", "ненавижу", "достал"), "angry", 0.8),
                 (("страшно", "опасно", "ужас", "боюсь"), "fear", 0.8),
                 (("неожиданно", "удивительно", "шок", "сенсация"), "surprised", 0.8),
                 (("устал", "устала", "нет сил", "выгорел"), "tired", 0.75),
                 (("спать хочу", "хочу спать", "сонный"), "sleepy", 0.75),
                 (("хентай", "эрот", "18+", "взросл", "клубнич", "аниме 18", "😏", "флирт", "раздень", "секс"), "flirty", 0.85))
        for keys, emotion, confidence in rules:
            if any(key in low for key in keys):
                return {"emotion": emotion, "anim": EMOTION_TO_ANIM.get(emotion, emotion),
                        "confidence": confidence, "source": "rules"}
        return {"emotion": "neutral", "anim": "neutral", "confidence": 0.0, "source": "fallback"}

    def _observe(self, text: str) -> Dict[str, Any]:
        now = time.time()
        result = self._analyze(text)
        emotion, confidence = result["emotion"], result["confidence"]
        threshold = float(self.app.get_plugin_setting(self.id, "confidence_threshold", 0.4)) if self.app else 0.4
        if now < self.until and self.emotion != "neutral" and (emotion == "neutral" or confidence < threshold) and confidence < 0.85:
            return {"emotion": self.emotion, "anim": self.anim, "confidence": self.confidence}
        if confidence >= threshold or emotion != "neutral" or now >= self.until:
            self.emotion, self.anim, self.confidence = emotion, result["anim"], confidence
            minimum = int(self.app.get_plugin_setting(self.id, "hold_seconds", 20)) if self.app else 20
            self.until = now + max(float(minimum), float(HOLD_SECONDS.get(emotion, 180)))
        return {"emotion": self.emotion, "anim": self.anim, "confidence": self.confidence}

    @staticmethod
    def _last_user_text(messages: List[Dict[str, Any]]) -> str:
        for message in reversed(messages or []):
            if message.get("role") == "user":
                return str(message.get("content") or "")
        return ""

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        self.app = app
        snapshot = self._observe(self._last_user_text(messages))
        app.state["emotion"] = snapshot["emotion"]
        app.state["emotion_animation"] = snapshot["anim"]
        app.state["emotion_confidence"] = snapshot["confidence"]
        if app.get_plugin_setting(self.id, "add_mood_to_prompt", True) and snapshot["emotion"] != "neutral":
            instruction = MOOD_INSTRUCTIONS.get(snapshot["emotion"])
            if instruction and messages and messages[0].get("role") == "system":
                messages[0]["content"] = str(messages[0].get("content") or "") + "\n\nЭмоциональный контекст:\n- " + instruction
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return reply
        self._apply_avatar(app)
        return reply

    def _apply_avatar(self, app: AppContext) -> None:
        avatar = app.plugins.get("avatar")
        if avatar is not None and hasattr(avatar, "apply_emotion"):
            avatar.apply_emotion(str(app.state.get("emotion_animation") or self.anim or "neutral"))
            return
        window = getattr(avatar, "win", None) if avatar is not None else None
        if window is None or not window.isVisible():
            return
        name = str(app.state.get("emotion_animation") or self.anim or "neutral")
        if not window.has(name):
            name = self.emotion if window.has(self.emotion) else "neutral"
        try:
            if window.has(name):
                frames = window._frames.get(name) or []
                if len(frames) > 1:
                    window.play(name, loop=False)
                else:
                    window.show_static(name)
        except Exception as exc:
            print(f"emotion avatar: {exc}", flush=True)


def register() -> PluginImpl:
    """Совместимость со старым загрузчиком plugins.<id>.plugin."""
    return PluginImpl()
