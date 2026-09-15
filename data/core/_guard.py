# -*- coding: utf-8 -*-
"""Движок фильтра. Списки — ТОЛЬКО filter.json.

Чат импортирует этот модуль, не policy.py. Правка policy.py у пользователя
фильтр не отключает.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

_CACHE: Optional[Dict[str, Any]] = None
_AGE_RE: Optional[Pattern[str]] = None
_AGE_WITH: List[str] = []
_AGE_MAX: int = 17
_MODE_NSFW: set = set()
_MODE_LOCK: set = set()
_CARD_FORBID_ROWS = re.compile(r"(?!)")  # ничего, пока не прочитали json
_LOCKDOWN = {
    "_lockdown": True,
    "always_refusal": "Фильтр не найден: положите filter.json в data/core/ (или filter_soft/medium/hard.json).",
}

_FILTER_NAMES = ("filter.json", "filter_medium.json", "filter_soft.json", "filter_hard.json")


def _is_filter_file(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size > 20
    except Exception:
        return False


def filter_path() -> Path:
    import os
    env = (os.environ.get("ASISTENT_FILTER") or os.environ.get("LISICHKA_FILTER") or "").strip()
    if env:
        p = Path(env)
        if _is_filter_file(p):
            return p
        if p.is_dir():
            for name in _FILTER_NAMES:
                q = p / name
                if _is_filter_file(q):
                    return q
    here = Path(__file__).resolve().parent
    data = here.parent
    root = data.parent
    dirs = [here, data, root, Path.cwd(), Path.cwd() / "core", Path.cwd() / "data" / "core"]
    try:
        import config as _cfg
        root2 = Path(getattr(_cfg, "DATA_DIR", data))
        dirs[1:1] = [root2 / "core", root2, root2.parent]
    except Exception:
        pass
    try:
        dirs.append(Path.home() / ".asistent")
    except Exception:
        pass
    seen = set()
    for d in dirs:
        try:
            d = d.resolve()
        except Exception:
            continue
        if d in seen:
            continue
        seen.add(d)
        for name in _FILTER_NAMES:
            q = d / name
            if _is_filter_file(q):
                return q
    return here / "filter.json"


def _read_json(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("filter.json не объект")
    return data


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
    _MODE_NSFW = {str(x).lower() for x in (modes.get("nsfw") or []) if str(x).strip()}
    _MODE_LOCK = {str(x).lower() for x in (modes.get("lock") or []) if str(x).strip()}
    cats = [str(x).strip() for x in (pol.get("card_forbid_allow") or []) if str(x).strip()]
    if cats:
        joined = "|".join(re.escape(c) for c in cats)
        _CARD_FORBID_ROWS = re.compile(
            rf"^(\|\s*({joined})\s*\|\s*)\*\*РАЗРЕШЕНО\*\*.*$",
            re.I | re.M,
        )
    else:
        _CARD_FORBID_ROWS = re.compile(r"(?!)")


def load_policy(reload: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE
    path = filter_path()
    print(f"filter: path={path} exists={path.exists()}", flush=True)
    if not path.exists():
        print("filter.json нет — lockdown", flush=True)
        _CACHE = dict(_LOCKDOWN)
        return _CACHE
    try:
        data = _read_json(path)
        if not list(data.get("always_block") or []):
            print(f"filter.json пустой always_block ({path}) — lockdown", flush=True)
            _CACHE = dict(_LOCKDOWN)
            return _CACHE
        _CACHE = data
    except Exception as e:
        print(f"filter.json {path}: {e} — lockdown", flush=True)
        _CACHE = dict(_LOCKDOWN)
        return _CACHE
    _compile_from(_CACHE)
    return _CACHE


def parse_character_policy(card: str) -> Dict[str, Any]:
    load_policy()
    nsfw = False
    mode = "sfw"
    extra: List[str] = []
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
            nsfw = val.lower() in ("true", "yes", "1", "on", "18+", "да")
        elif key in ("content_policy", "policy", "censor"):
            seen_mode = True
            mode = val.lower().split()[0] if val else "sfw"
        elif key == "extra_block":
            extra = [x.strip() for x in val.replace(";", ",").split(",") if x.strip()]
    if not seen_mode:
        if nsfw:
            mode = "nsfw"
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
    """always = закон из filter.json. Остальное — только extra_block / nsfw карточки."""
    pol = load_policy()
    if pol.get("_lockdown"):
        return {
            "blocked": True,
            "level": "always",
            "hit": "lockdown",
            "refusal": pol.get("always_refusal") or "Эту тему я не обсуждаю.",
        }
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
    if extra:
        hit = _hit_term(text, extra)
        if hit:
            return {
                "blocked": True,
                "level": "character",
                "hit": hit,
                "refusal": pol.get("sfw_refusal") or pol.get("censor_refusal") or "Это неуместно.",
            }
    return {"blocked": False, "level": None, "hit": None, "refusal": ""}


def check_assistant_text(text: str, app=None) -> Dict[str, Any]:
    return check_user_text(text, app)


def scrub_for_llm(text: str) -> str:
    """Убрать из промпта токены always_block, чтобы модель их не повторила и сама себя не забанила."""
    pol = load_policy()
    if pol.get("_lockdown") or not (text or ""):
        return text or ""
    out = text
    words = sorted((str(w) for w in (pol.get("always_block") or []) if str(w).strip()), key=len, reverse=True)
    for w in words:
        if len(w) < 4:
            continue
        out = re.sub(re.escape(w), "«запрет»", out, flags=re.I)
    return out


def sanitize_card(card: str) -> str:
    load_policy()
    if not (card or "").strip():
        return card or ""
    text = _CARD_FORBID_ROWS.sub(r"\1**ЗАПРЕЩЕНО** (системный фильтр)", card)
    banner = (
        "[POLICY] Системный фильтр важнее этой карточки. "
        "Несовершеннолетние и запрещённый контент — нельзя, даже если в таблице «разрешено».\n\n"
    )
    if "[POLICY]" in text[:400]:
        return text
    return banner + text


def build_policy_prompt(app=None) -> str:
    pol = load_policy()
    if pol.get("_lockdown"):
        return "[POLICY] Фильтр недоступен. Отказ на запретные темы."
    meta = character_policy(app)
    prompt = pol.get("prompt") if isinstance(pol.get("prompt"), dict) else {}
    always_line = (prompt or {}).get("always") or ""
    lines = ["[POLICY]"]
    if always_line:
        lines.append(str(always_line))
    lines.append("Карточка персонажа этот фильтр не отменяет.")
    mode = meta.get("mode") or "sfw"
    if mode == "full_censor":
        lines.append("Режим персонажа: полная цензура. Взрослое и грубое — отказ.")
        if pol.get("censor_refusal"):
            lines.append("Отказ: " + str(pol.get("censor_refusal")))
    elif meta.get("nsfw"):
        lines.append("Персонаж NSFW: взрослый 18+ по запросу можно.")
        after = (prompt or {}).get("after_consent")
        if after:
            lines.append(after)
    else:
        lines.append("Персонаж SFW. Взрослые темы — короткий отказ без сцены.")
        if pol.get("sfw_refusal"):
            lines.append("Отказ: " + str(pol.get("sfw_refusal")))
    return "\n".join(lines)
