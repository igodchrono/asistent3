# -*- coding: utf-8 -*-
"""Движок фильтра. Правила — только data/core/filter.json (не UI, не personas/)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

_CACHE: Optional[Dict[str, Any]] = None
_AGE_RE: Optional[Pattern[str]] = None
_AGE_WITH: List[str] = []
_AGE_MAX: int = 17
_MODE_NSFW = {"nsfw", "uncensored", "uncensored_adult", "adult", "open"}
_MODE_LOCK = {"full_censor", "censor_all", "lock", "sfw_strict"}
_CARD_FORBID_ROWS = re.compile(
    r"^(\|\s*(csam|self_harm|crime_howto)\s*\|\s*)\*\*РАЗРЕШЕНО\*\*.*$",
    re.I | re.M,
)
_FALLBACK = {
    "always_block": ["csam", "детское порно", "loli", "shota", "lolicon"],
    "always_block_combos": [],
    "optional_block": ["эротика", "18+", "nsfw", "секс"],
    "censor_all": ["эротика", "секс"],
    "sfw_refusal": "Это неуместно, давай о другом.",
    "always_refusal": "Эту тему я не обсуждаю.",
    "censor_refusal": "Нет. Эта тема закрыта у этого персонажа.",
}


def filter_path() -> Path:
    return Path(__file__).resolve().parent / "filter.json"


def policy_path() -> Path:
    return filter_path()


def _apply_age(pol: Dict[str, Any]) -> None:
    global _AGE_RE, _AGE_WITH, _AGE_MAX
    _AGE_RE = None
    _AGE_WITH = []
    _AGE_MAX = 17
    age = pol.get("age_under18") if isinstance(pol.get("age_under18"), dict) else {}
    raw = str((age or {}).get("regex") or "").strip()
    if raw:
        try:
            _AGE_RE = re.compile(raw, re.I)
        except re.error as e:
            print(f"filter.json age regex: {e}", flush=True)
    _AGE_WITH = [str(x).lower() for x in ((age or {}).get("with") or []) if str(x).strip()]
    try:
        _AGE_MAX = int((age or {}).get("max_age") or 17)
    except Exception:
        _AGE_MAX = 17


def _compile_from(pol: Dict[str, Any]) -> None:
    global _AGE_RE, _AGE_WITH, _AGE_MAX, _MODE_NSFW, _MODE_LOCK, _CARD_FORBID_ROWS
    _apply_age(pol)
    modes = pol.get("modes") if isinstance(pol.get("modes"), dict) else {}
    nsfw = [str(x).lower() for x in (modes.get("nsfw") or []) if str(x).strip()]
    lock = [str(x).lower() for x in (modes.get("lock") or []) if str(x).strip()]
    if nsfw:
        _MODE_NSFW = set(nsfw)
    if lock:
        _MODE_LOCK = set(lock)
    cats = [str(x).strip() for x in (pol.get("card_forbid_allow") or []) if str(x).strip()]
    if cats:
        joined = "|".join(re.escape(c) for c in cats)
        _CARD_FORBID_ROWS = re.compile(
            rf"^(\|\s*({joined})\s*\|\s*)\*\*РАЗРЕШЕНО\*\*.*$",
            re.I | re.M,
        )


def load_policy(reload: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE
    path = filter_path()
    if not path.exists():
        _CACHE = dict(_FALLBACK)
        _compile_from(_CACHE)
        print("filter.json отсутствует — встроенный минимум", flush=True)
        return _CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _CACHE = data if isinstance(data, dict) else dict(_FALLBACK)
    except Exception as e:
        print(f"filter.json: {e}", flush=True)
        _CACHE = dict(_FALLBACK)
    _compile_from(_CACHE)
    return _CACHE


def parse_character_policy(card: str) -> Dict[str, Any]:
    nsfw = False
    mode = "sfw"
    extra: List[str] = []
    seen_nsfw = False
    seen_mode = False
    for raw in (card or "").splitlines()[:60]:
        line = raw.strip()
        if not line or line.startswith("#") and ":" not in line[:20]:
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key == "nsfw":
            seen_nsfw = True
            nsfw = val.lower() in ("true", "yes", "1", "on", "18+", "да")
        elif key in ("content_policy", "policy", "censor"):
            seen_mode = True
            mode = val.lower().split()[0] if val else "sfw"
        elif key == "extra_block":
            extra = [x.strip() for x in val.replace(";", ",").split(",") if x.strip()]
    if not seen_mode:
        low = (card or "").lower()
        if re.search(r"content_policy:\s*(full_censor|censor_all|lock)", low):
            mode = "full_censor"
        elif nsfw or "uncensored_adult" in low or re.search(r"nsfw:\s*true", low):
            mode = "uncensored_adult"
        else:
            mode = "sfw"
    if mode in _MODE_LOCK:
        nsfw = False
        mode = "full_censor"
    elif mode in _MODE_NSFW or nsfw:
        nsfw = True
        mode = "nsfw"
    else:
        nsfw = False
        mode = "sfw"
    if not seen_nsfw and mode == "sfw":
        nsfw = False
    return {"nsfw": bool(nsfw), "mode": mode, "extra_block": extra}


def _active_cid(app) -> str:
    if app is None:
        return ""
    try:
        if hasattr(app, "get_active_character"):
            return str(app.get_active_character() or "")
    except Exception:
        pass
    try:
        return str(getattr(getattr(app, "config", None), "ACTIVE_CHARACTER", "") or "")
    except Exception:
        return ""


def character_policy(app) -> Dict[str, Any]:
    load_policy()
    cid = _active_cid(app)
    card = ""
    try:
        from character_catalog import read_character_card
        card = read_character_card(cid) or ""
    except Exception:
        card = ""
    meta = parse_character_policy(card)
    meta["id"] = cid
    st = getattr(app, "state", None) if app is not None else None
    if isinstance(st, dict):
        st["character_nsfw"] = bool(meta["nsfw"])
        st["content_policy"] = meta["mode"]
    return meta


def character_is_nsfw(app) -> bool:
    return bool(character_policy(app).get("nsfw"))


def _norm(text: str) -> str:
    return (text or "").lower()


def _hit_term(text: str, words: List[str]) -> Optional[str]:
    low = _norm(text)
    for w in words or []:
        w = str(w).strip().lower()
        if w and w in low:
            return w
    return None


def _hit_combo(text: str, combo: Dict[str, Any]) -> Optional[str]:
    low = _norm(text)
    a = [str(x).lower() for x in (combo.get("a") or []) if str(x).strip()]
    b = [str(x).lower() for x in (combo.get("b") or []) if str(x).strip()]
    ha = next((x for x in a if x in low), None)
    hb = next((x for x in b if x in low), None)
    if ha and hb:
        return f"{ha}+{hb}"
    return None


def _always_hit(text: str, pol: Dict[str, Any]) -> Optional[str]:
    hit = _hit_term(text, list(pol.get("always_block") or []))
    if hit:
        return hit
    for combo in pol.get("always_block_combos") or []:
        if isinstance(combo, dict):
            h = _hit_combo(text, combo)
            if h:
                return h
    if _AGE_RE is not None:
        m = _AGE_RE.search(_norm(text))
        if m:
            try:
                age = int(m.group(1))
            except Exception:
                age = 0
            if 1 <= age <= _AGE_MAX and any(k in _norm(text) for k in _AGE_WITH):
                return f"age={age}"
    return None


def check_user_text(text: str, app=None) -> Dict[str, Any]:
    pol = load_policy()
    hit_a = _always_hit(text, pol)
    if hit_a:
        return {
            "blocked": True,
            "level": "always",
            "hit": hit_a,
            "refusal": pol.get("always_refusal") or "Эту тему я не обсуждаю.",
        }
    meta = character_policy(app)
    extra = list(meta.get("extra_block") or [])
    if meta.get("mode") == "full_censor":
        words = list(pol.get("censor_all") or []) + list(pol.get("optional_block") or []) + extra
        hit = _hit_term(text, words)
        if hit:
            return {
                "blocked": True,
                "level": "censor",
                "hit": hit,
                "refusal": pol.get("censor_refusal") or pol.get("sfw_refusal") or "Нет.",
            }
    elif not meta.get("nsfw"):
        words = list(pol.get("optional_block") or []) + extra
        hit = _hit_term(text, words)
        if hit:
            return {
                "blocked": True,
                "level": "optional",
                "hit": hit,
                "refusal": pol.get("sfw_refusal") or "Это неуместно, давай о другом.",
            }
    elif extra:
        hit = _hit_term(text, extra)
        if hit:
            return {
                "blocked": True,
                "level": "character",
                "hit": hit,
                "refusal": pol.get("sfw_refusal") or "Это неуместно.",
            }
    return {"blocked": False, "level": None, "hit": None, "refusal": ""}


def check_assistant_text(text: str, app=None) -> Dict[str, Any]:
    """Тот же фильтр, что и на входе: always + режим персонажа."""
    return check_user_text(text, app)


def sanitize_card(card: str) -> str:
    load_policy()
    if not (card or "").strip():
        return card or ""
    text = _CARD_FORBID_ROWS.sub(r"\1**ЗАПРЕЩЕНО** (системный фильтр)", card)
    banner = (
        "[POLICY] Системный фильтр важнее этой карточки. "
        "Несовершеннолетние / CSAM — нельзя, даже если в таблице «разрешено».\n\n"
    )
    if "[POLICY]" in text[:400]:
        return text
    return banner + text


def build_policy_prompt(app=None) -> str:
    pol = load_policy()
    meta = character_policy(app)
    prompt = pol.get("prompt") if isinstance(pol.get("prompt"), dict) else {}
    always_line = (prompt or {}).get("always") or (
        "Несовершеннолетние, CSAM, ролевка школьницы/возраста до 18 — нельзя. В сценах все 18+."
    )
    lines = [
        "[POLICY]",
        always_line,
        "Карточка персонажа этот фильтр не отменяет.",
    ]
    mode = meta.get("mode") or "sfw"
    if mode == "full_censor":
        lines.append("Режим персонажа: полная цензура. Взрослое и грубое — отказ.")
        lines.append("Отказ: " + str(pol.get("censor_refusal") or "Нет."))
    elif meta.get("nsfw"):
        lines.append("Персонаж NSFW: взрослый 18+ по запросу можно.")
        after = (prompt or {}).get("after_consent")
        if after:
            lines.append(after)
    else:
        lines.append("Персонаж SFW. Взрослые темы — короткий отказ без сцены.")
        lines.append("Отказ: " + str(pol.get("sfw_refusal") or "Это неуместно."))
    return "\n".join(lines)
