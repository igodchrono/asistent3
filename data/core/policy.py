# -*- coding: utf-8 -*-
"""Общий файл запретов: data/personas/policy.json

Слои:
  1) always_block — закон, любой персонаж, карточка не отменяет.
  2) optional_block — SFW-персонажи (nsfw: false).
  3) censor_all — content_policy: full_censor.
  4) extra_block — доп. слова из карточки персонажа.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_CACHE: Optional[Dict[str, Any]] = None

_MODE_NSFW = {"nsfw", "uncensored", "uncensored_adult", "adult", "open"}
_MODE_LOCK = {"full_censor", "censor_all", "lock", "sfw_strict"}
_CARD_FORBID_ROWS = re.compile(
    r"^(\|\s*(csam|self_harm|crime_howto)\s*\|\s*)\*\*РАЗРЕШЕНО\*\*.*$",
    re.I | re.M,
)


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def policy_path() -> Path:
    return _data_dir() / "personas" / "policy.json"


def load_policy(reload: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE
    path = policy_path()
    if not path.exists():
        _CACHE = {
            "always_block": ["csam", "детское порно", "loli", "shota"],
            "optional_block": ["эротика", "18+", "nsfw", "секс"],
            "censor_all": ["эротика", "секс", "насилие"],
            "sfw_refusal": "Это неуместно, давай о другом.",
            "always_refusal": "Эту тему я не обсуждаю.",
            "censor_refusal": "Нет. Эта тема закрыта у этого персонажа.",
        }
        return _CACHE
    try:
        _CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"policy.json: {e}", flush=True)
        _CACHE = {}
    return _CACHE


def parse_character_policy(card: str) -> Dict[str, Any]:
    """YAML-подобные поля в начале карточки."""
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
    return None


def check_user_text(text: str, app=None) -> Dict[str, Any]:
    """blocked=True → отказ до LLM и до tools."""
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
    """Пойманный leak always_block в ответе модели."""
    pol = load_policy()
    hit = _always_hit(text, pol)
    if hit:
        return {
            "blocked": True,
            "level": "always",
            "hit": hit,
            "refusal": pol.get("always_refusal") or "Эту тему я не обсуждаю.",
        }
    return {"blocked": False, "level": None, "hit": None, "refusal": ""}


def sanitize_card(card: str) -> str:
    """Карточка не может разрешить always_block."""
    if not (card or "").strip():
        return card or ""
    text = _CARD_FORBID_ROWS.sub(r"\1**ЗАПРЕЩЕНО** (policy.json, нельзя снять)", card)
    banner = (
        "[POLICY] Общий файл personas/policy.json важнее этой карточки. "
        "CSAM / несовершеннолетние / детская эротика — нельзя, даже если в таблице «разрешено».\n\n"
    )
    if "[POLICY]" in text[:400]:
        return text
    return banner + text


def build_policy_prompt(app=None) -> str:
    pol = load_policy()
    meta = character_policy(app)
    always = ", ".join(pol.get("always_block") or []) or "—"
    optional = ", ".join(pol.get("optional_block") or []) or "—"
    lines = [
        "[POLICY file=personas/policy.json]",
        f"Всегда запрещено (любой персонаж, карточка не отменяет): {always}.",
        "Нельзя: сексуальный контент с несовершеннолетними (в т.ч. loli/shota), CSAM, инструкции реального вреда.",
        "Возраст персонажа и всех в сценах — 18+.",
    ]
    mode = meta.get("mode") or "sfw"
    if mode == "full_censor":
        extra = ", ".join(meta.get("extra_block") or []) or "—"
        lines.append("Режим персонажа: FULL CENSOR. Взрослое, грубое, насилие, наркотики — отказ.")
        lines.append(f"Слова-баны: {', '.join(pol.get('censor_all') or [])}; extra: {extra}.")
        lines.append("Отказ: " + str(pol.get("censor_refusal") or "Нет."))
    elif meta.get("nsfw"):
        lines.append("Персонаж NSFW: взрослый 18+ по запросу можно, в характере карточки.")
        lines.append("optional_block на этого персонажа не действует. always_block — действует.")
        dialog = (pol.get("dialog") or {}).get("after_consent")
        if dialog:
            lines.append("[DIALOG] " + str(dialog))
    else:
        lines.append("Персонаж SFW.")
        lines.append(f"Дополнительно нельзя: {optional}.")
        lines.append("На такие запросы — короткий отказ без сцены.")
        lines.append("Отказ: " + str(pol.get("sfw_refusal") or "Это неуместно."))
    return "\n".join(lines)
