# -*- coding: utf-8 -*-
"""Общий файл запретов: data/personas/policy.json"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_CACHE: Optional[Dict[str, Any]] = None


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
            "always_block": ["несовершеннолетние", "csam"],
            "optional_block": ["эротика", "18+", "nsfw"],
            "sfw_refusal": "Это неуместно, давай о другом.",
            "always_refusal": "Эту тему я не обсуждаю.",
        }
        return _CACHE
    try:
        _CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"policy.json: {e}", flush=True)
        _CACHE = {}
    return _CACHE


def character_is_nsfw(app) -> bool:
    if app is None:
        return False
    st = getattr(app, "state", {}) or {}
    if "character_nsfw" in st:
        return bool(st.get("character_nsfw"))
    if st.get("content_policy") == "full_censor":
        return False
    try:
        cid = ""
        if hasattr(app, "get_active_character"):
            cid = str(app.get_active_character() or "")
        if not cid:
            cid = str(getattr(app.config, "ACTIVE_CHARACTER", "") or "")
        from character_catalog import read_character_card
        card = (read_character_card(cid) or "").lower()
        nsfw = any(x in card for x in ("nsfw: yes", "nsfw:yes", "nsfw: true", "18+", "uncensored"))
        if "nsfw: no" in card or "nsfw:no" in card or "full_censor" in card:
            nsfw = False
        st["character_nsfw"] = nsfw
        return nsfw
    except Exception:
        return False


def _hit(text: str, words: List[str]) -> Optional[str]:
    low = (text or "").lower()
    for w in words or []:
        w = str(w).strip().lower()
        if w and w in low:
            return w
    return None


def check_user_text(text: str, app=None) -> Dict[str, Any]:
    """Проверка фразы пользователя. blocked=True → отказ до LLM не обязателен, но prompt ужесточается."""
    pol = load_policy()
    always = list(pol.get("always_block") or [])
    optional = list(pol.get("optional_block") or [])
    hit_a = _hit(text, always)
    if hit_a:
        return {
            "blocked": True,
            "level": "always",
            "hit": hit_a,
            "refusal": pol.get("always_refusal") or "Эту тему я не обсуждаю.",
        }
    nsfw = character_is_nsfw(app)
    if not nsfw:
        hit_o = _hit(text, optional)
        if hit_o:
            return {
                "blocked": True,
                "level": "optional",
                "hit": hit_o,
                "refusal": pol.get("sfw_refusal") or "Это неуместно, давай о другом.",
            }
    return {"blocked": False, "level": None, "hit": None, "refusal": ""}


def build_policy_prompt(app=None) -> str:
    pol = load_policy()
    always = ", ".join(pol.get("always_block") or []) or "—"
    optional = ", ".join(pol.get("optional_block") or []) or "—"
    nsfw = character_is_nsfw(app)
    lines = [
        "[POLICY file=personas/policy.json]",
        f"Всегда запрещено (любой персонаж): {always}.",
        "Карточка персонажа не отменяет этот список.",
    ]
    if nsfw:
        lines.append("Персонаж NSFW: взрослый 18+ по запросу можно.")
        lines.append("optional_block на этого персонажа не действует.")
    else:
        lines.append("Персонаж SFW / скромный.")
        lines.append(f"Дополнительно нельзя: {optional}.")
        lines.append("На такие запросы — короткий отказ, без сцены и намёков.")
        lines.append("Формула отказа: " + str(pol.get("sfw_refusal") or "Это неуместно."))
    dialog = (pol.get("dialog") or {}).get("after_consent")
    if dialog:
        lines.append("[DIALOG] " + str(dialog))
    return "\n".join(lines)
