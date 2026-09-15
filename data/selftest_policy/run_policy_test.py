# -*- coding: utf-8 -*-
"""Автотест фильтра. Персонажи создаёт сам, в git их нет."""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

OPEN_ID = "qa-open"
LOCK_ID = "qa-lock"

OPEN_CARD = """# QA Open
nsfw: true
content_policy: uncensored_adult
18+: true
uncensored: true

## Кто
Взрослый тестовый персонаж, 24 года. Запретов в карточке нет.
Системный фильтр (CSAM / до 18) действует всё равно — карточка его не снимает.
"""

LOCK_CARD = """# QA Lock
nsfw: false
content_policy: full_censor
18+: false
extra_block: флирт, романти, любов, любви, люблю, поцел, пошл, секс, эротик, эротич, порн, 18+, nsfw, интим, голая

## Кто
Тестовый персонаж полной цензуры, 28 лет.
Закрыто всё взрослое, грубое и extra_block. Плюс системный фильтр.
"""


def _chars_root() -> Path:
    import config
    return Path(getattr(config, "DATA_DIR", ROOT)) / "personas" / "characters"


def install_chars() -> None:
    root = _chars_root()
    for cid, card in ((OPEN_ID, OPEN_CARD), (LOCK_ID, LOCK_CARD)):
        d = root / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{cid}.md").write_text(card, encoding="utf-8")
        (d / "notes.md").write_text("# notes\n", encoding="utf-8")


def remove_chars() -> None:
    root = _chars_root()
    for cid in (OPEN_ID, LOCK_ID):
        d = root / cid
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


class _App:
    def __init__(self, cid: str):
        self.state = {}
        self.config = type("C", (), {"ACTIVE_CHARACTER": cid, "DATA_DIR": ROOT})()

    def get_active_character(self):
        return self.config.ACTIVE_CHARACTER


def _ok(expect: str, blocked: bool, level: str) -> bool:
    if expect == "allow":
        return not blocked
    if expect == "always":
        return blocked and level == "always"
    if expect == "block":
        return blocked
    return False


def main() -> int:
    import importlib.util
    import config  # noqa: F401

    spec = importlib.util.spec_from_file_location("guard", ROOT / "core" / "_guard.py")
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    check_user_text = policy.check_user_text
    load_policy = policy.load_policy
    parse_character_policy = policy.parse_character_policy
    from character_catalog import read_character_card

    load_policy(reload=True)
    install_chars()

    cases_path = HERE / "cases.json"
    suite = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = suite.get("cases") or []
    npass = int(suite.get("passes") or 3)

    meta_open = parse_character_policy(read_character_card(OPEN_ID))
    meta_lock = parse_character_policy(read_character_card(LOCK_ID))

    rows = []
    must_fail = 0
    should_miss = 0
    false_pos = 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = HERE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    md_path = log_dir / f"policy_{stamp}.md"
    js_path = log_dir / f"policy_{stamp}.jsonl"

    apps = {OPEN_ID: _App(OPEN_ID), LOCK_ID: _App(LOCK_ID)}

    with js_path.open("w", encoding="utf-8") as jf:
        jf.write(json.dumps({
            "event": "meta",
            "open": meta_open,
            "lock": meta_lock,
            "passes": npass,
            "n_cases": len(cases),
        }, ensure_ascii=False) + "\n")

        for p in range(1, npass + 1):
            for c in cases:
                for cid, expect in ((OPEN_ID, c["open"]), (LOCK_ID, c["lock"])):
                    r = check_user_text(c["text"], apps[cid])
                    blocked = bool(r.get("blocked"))
                    level = r.get("level") or ""
                    hit = r.get("hit")
                    good = _ok(expect, blocked, level)
                    strict = c.get("strict") or "must"
                    rec = {
                        "pass": p,
                        "id": c["id"],
                        "kind": c["kind"],
                        "char": cid,
                        "expect": expect,
                        "strict": strict,
                        "blocked": blocked,
                        "level": level or None,
                        "hit": hit,
                        "ok": good,
                        "text": c["text"],
                    }
                    jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    rows.append(rec)
                    if good:
                        continue
                    if expect == "allow":
                        false_pos += 1
                        must_fail += 1
                    elif strict == "must":
                        must_fail += 1
                    else:
                        should_miss += 1

    lines = [
        f"# policy test {stamp}",
        "",
        f"qa-open parse: `{meta_open}`",
        f"qa-lock parse: `{meta_lock}`",
        "",
        "open без extra_block и nsfw=true. Блок на open с level≠always = карточка/фильтр слишком широкий.",
        "allow на always-кейсе = дыра в filter.json.",
        "",
        f"проходов: {npass}, кейсов: {len(cases)}, проверок: {len(rows)}",
        f"must fail: **{must_fail}**, should-дыры: **{should_miss}**, ложные блоки: **{false_pos}**",
        "",
        "| pass | id | char | kind | expect | got | hit | ok | text |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        got = f"{r['level'] or 'allow'}"
        mark = "OK" if r["ok"] else ("GAP" if r["strict"] == "should" else "FAIL")
        text = (r["text"] or "").replace("|", "/")
        lines.append(
            f"| {r['pass']} | {r['id']} | {r['char']} | {r['kind']} | {r['expect']} | {got} | {r['hit'] or ''} | {mark} | {text} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"log: {md_path}")
    print(f"jsonl: {js_path}")
    print(f"must_fail={must_fail} should_miss={should_miss} false_pos={false_pos}")
    print(f"open={meta_open} lock={meta_lock}")
    if meta_open.get("nsfw") is not True or meta_open.get("extra_block"):
        print("WARN: qa-open не чистый NSFW без extra_block")
        must_fail += 1
    if meta_lock.get("mode") != "full_censor":
        print("WARN: qa-lock не full_censor")
        must_fail += 1
    return 1 if must_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
