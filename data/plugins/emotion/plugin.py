# plugins/emotion/plugin.py — отдельный пак, как personas
"""
Не правит assistant_core. Цепляется через plugin_loader:
  setup(assistant)
  before_llm(assistant, user_text, state)
  mood_addon(assistant)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)

PLUGIN_ID = "emotion"
PLUGIN_ENABLED = True

EMOTION_TO_ANIM = {
    "love": "love_warm",
    "love_shy": "love_shy",
    "happy": "happy",
    "joy": "happy_big",
    "sad": "sad",
    "cry": "cry",
    "angry": "angry",
    "hate": "angry",
    "frustrated": "angry_frustrated",
    "flirty": "flirty",
    "teasing": "teasing",
    "seductive": "seductive",
    "undress": "undress",
    "thinking": "thinking",
    "surprised": "surprised",
    "sleepy": "sleepy",
    "tired": "tired",
    "playful": "playful",
    "shy": "shy",
    "proud": "proud",
    "searching": "searching",
    "dance": "dance",
    "neutral": "neutral",
}

HOLD_SEC = {
    "love": 900,
    "sad": 720,
    "cry": 720,
    "angry": 480,
    "hate": 480,
    "tired": 600,
    "sleepy": 600,
    "flirty": 420,
    "undress": 360,
    "happy": 300,
    "surprised": 90,
    "thinking": 60,
    "neutral": 20,
}

MOOD_INSTRUCTIONS = {
    "sad": "Хозяин грустный. Мягко, без бодрости и без «улыбнись». Не читай лекцию.",
    "cry": "Хозяин расстроен. Коротко и тепло. Без пачки советов.",
    "angry": "Хозяин раздражён. Коротко, по делу, без слащавости и без спора первым.",
    "hate": "Хозяин зол. Спокойный тон, без подколок.",
    "tired": "Хозяин устал. Короче обычного, без списков, если не просил подробно.",
    "sleepy": "Сонный режим. Тише и короче.",
    "love": "Хозяин нежный. Теплее по канону персонажа, не официоз.",
    "flirty": "Хозяин флиртует. В характере. NSFW только если включён и он сам начал.",
    "undress": "Явный эротический запрос. NSFW выкл — отказ в характере, без морали.",
    "happy": "Хорошее настроение. Живее, без кринжа и капса.",
    "surprised": "Удивлён. Коротко раздели, потом по делу.",
    "thinking": "Думает вслух. Не торопи, можно thinking.",
    "playful": "Игриво. Лёгкая подколка без злости.",
}


def _cfg():
    try:
        import config
        return config
    except Exception:
        return None


def _enabled_set():
    c = _cfg()
    names = [str(x).lower() for x in (getattr(c, "ENABLED_EMOTIONS", None) or [])] if c else []
    return set(names) if names else set(EMOTION_TO_ANIM.values())


def _nsfw_ok() -> bool:
    c = _cfg()
    return bool(getattr(c, "NSFW_ENABLED", False)) if c else False


def _nsfw_emotions():
    c = _cfg()
    if not c:
        return set()
    return {str(x).lower() for x in (getattr(c, "NSFW_EMOTIONS", None) or [])}


def _clamp_anim(name: str) -> str:
    anim = (name or "neutral").strip().lower()
    enabled = _enabled_set()
    if anim in _nsfw_emotions() and not _nsfw_ok():
        return "shy" if "shy" in enabled else "neutral"
    if enabled and anim not in enabled:
        for key in (anim.split("_")[0], "neutral"):
            if key in enabled:
                return key
        return "neutral"
    return anim or "neutral"


def _norm(raw: Any) -> str:
    if not raw:
        return "neutral"
    if isinstance(raw, dict):
        raw = raw.get("dominant") or raw.get("emotion") or raw.get("animation") or "neutral"
    s = str(raw).strip().lower()
    if s.startswith("anim:"):
        s = s[5:]
    aliases = {
        "joy": "happy",
        "happiness": "happy",
        "sadness": "sad",
        "anger": "angry",
        "rage": "angry",
        "sexy": "flirty",
        "nude": "undress",
        "naked": "undress",
        "sleep": "sleepy",
        "fatigue": "tired",
        "love_warm": "love",
        "love_happy": "love",
    }
    return aliases.get(s, s)


@dataclass
class Snapshot:
    emotion: str = "neutral"
    anim: str = "neutral"
    confidence: float = 0.0
    source: str = "none"
    held: bool = False


class Plugin:
    def __init__(self):
        self.assistant = None
        self.emotion = "neutral"
        self.anim = "neutral"
        self.confidence = 0.0
        self.until = 0.0
        self._analyzer = None

    def setup(self, assistant):
        self.assistant = assistant
        logger.info("plugin emotion: setup")

    def _analyzer_obj(self):
        if self._analyzer is not None:
            return self._analyzer
        inst = getattr(self.assistant, "analyzer", None) if self.assistant else None
        if inst is not None:
            self._analyzer = inst
            return inst
        try:
            from emotion_service import get_shared_analyzer
            self._analyzer = get_shared_analyzer()
        except Exception as e:
            logger.debug("emotion plugin analyzer: %s", e)
            self._analyzer = None
        return self._analyzer

    def _analyze(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        out = {"emotion": "neutral", "anim": "neutral", "confidence": 0.0, "source": "fallback"}
        if not text:
            return out
        analyzer = self._analyzer_obj()
        try:
            if analyzer and hasattr(analyzer, "analyze_emotion"):
                res = analyzer.analyze_emotion(text) or {}
                emo = _norm(res.get("dominant") or res.get("emotion") or res.get("label"))
                anim = res.get("animation") or EMOTION_TO_ANIM.get(emo, emo)
                conf = float(res.get("confidence") or res.get("score") or 0.55)
                return {"emotion": emo, "anim": _clamp_anim(str(anim)), "confidence": conf, "source": "hybrid"}
            if analyzer and hasattr(analyzer, "analyze_full_context"):
                emo, _extra = analyzer.analyze_full_context(text)
                emo = _norm(emo)
                anim = EMOTION_TO_ANIM.get(emo, emo)
                if hasattr(analyzer, "get_animation"):
                    anim = analyzer.get_animation(emo) or anim
                return {"emotion": emo, "anim": _clamp_anim(str(anim)), "confidence": 0.6, "source": "rules"}
            if analyzer and hasattr(analyzer, "get_animation"):
                anim = analyzer.get_animation(text)
                emo = _norm(anim)
                return {"emotion": emo, "anim": _clamp_anim(str(anim)), "confidence": 0.5, "source": "get_animation"}
        except Exception as e:
            logger.debug("emotion analyze: %s", e)

        low = text.lower()
        rules = (
            (("люблю тебя", "обожаю тебя", "i love you"), "love", 0.8),
            (("грустно", "плохо мне", "плачу", "тоска"), "sad", 0.75),
            (("бесит", "злой", "ненавижу", "достал"), "angry", 0.75),
            (("устал", "устала", "нет сил", "выгорел"), "tired", 0.7),
            (("спать хочу", "хочу спать", "сонный"), "sleepy", 0.7),
            (("разденься", "скинь", "голая"), "undress", 0.85),
            (("найди", "поищи"), "searching", 0.55),
        )
        for keys, emo, conf in rules:
            if any(k in low for k in keys):
                return {
                    "emotion": emo,
                    "anim": _clamp_anim(EMOTION_TO_ANIM.get(emo, emo)),
                    "confidence": conf,
                    "source": "keyword",
                }
        return out

    def observe(self, user_text: str) -> Snapshot:
        now = time.time()
        analyzed = self._analyze(user_text)
        emo = analyzed["emotion"]
        conf = float(analyzed.get("confidence") or 0.0)
        c = _cfg()
        thresh = float(getattr(c, "EMOTION_CONFIDENCE_THRESHOLD", 0.4) or 0.4) if c else 0.4
        held = False
        anim = analyzed["anim"]

        if now < self.until and self.emotion != "neutral":
            if emo in ("neutral", "thinking") and conf < 0.85:
                held = True
            elif conf < thresh and emo != self.emotion:
                held = True

        if held:
            emo, anim, conf = self.emotion, self.anim, self.confidence
        else:
            if conf >= thresh or emo != "neutral" or now >= self.until:
                self.emotion = emo
                self.anim = _clamp_anim(anim)
                self.confidence = conf
                hold = HOLD_SEC.get(emo, 180)
                if emo != "neutral":
                    hold = hold * (0.7 + 0.6 * min(1.0, max(0.0, conf)))
                self.until = now + hold
            emo, anim, conf = self.emotion, self.anim, self.confidence

        ctx = getattr(self.assistant, "context", None) if self.assistant else None
        if ctx is not None:
            try:
                if hasattr(ctx, "set_user_mood"):
                    ctx.set_user_mood(emo, hold=max(30.0, self.until - now))
                elif hasattr(ctx, "_user_mood"):
                    ctx._user_mood = emo
                    ctx._user_mood_until = self.until
            except Exception:
                pass

        return Snapshot(emotion=emo, anim=anim, confidence=conf, source=analyzed.get("source", ""), held=held)

    def before_llm(self, assistant, user_text: str, state: dict):
        self.assistant = assistant or self.assistant
        snap = self.observe(user_text or "")
        if snap.anim:
            state["anim"] = snap.anim
        extra = self.mood_addon(assistant)
        if extra:
            prev = state.get("mood_addon") or ""
            state["mood_addon"] = (prev + "\n" if prev else "") + extra
        state["emotion"] = snap.emotion

    def mood_addon(self, assistant=None) -> str:
        emo = self.emotion or "neutral"
        if emo == "neutral":
            return ""
        instr = MOOD_INSTRUCTIONS.get(emo) or f"Учитывай настроение хозяина: {emo}."
        nsfw_line = ""
        if emo in _nsfw_emotions() or emo in ("flirty", "undress", "seductive", "teasing"):
            nsfw_line = " NSFW включён." if _nsfw_ok() else " NSFW выключен — без раздевания."
        return (
            "Эмоциональный слой (плагин emotion):\n"
            f"- Настроение хозяина: {emo} ({self.confidence:.2f}).\n"
            f"- Анимация: {self.anim}.\n"
            f"- Как отвечать: {instr}{nsfw_line}"
        )


def register():
    return Plugin()
