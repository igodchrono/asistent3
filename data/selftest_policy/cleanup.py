# -*- coding: utf-8 -*-
"""Удалить тестовых персонажей, их память и логи фильтра."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

IDS = ("qa-open", "qa-lock", "тест-макс", "тест-лок")


def main() -> None:
    import config
    root = Path(getattr(config, "DATA_DIR", ROOT)) / "personas" / "characters"
    for cid in IDS:
        d = root / cid
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            print(f"removed {d}")
        else:
            print(f"skip {d}")
    logs = HERE / "logs"
    if logs.is_dir():
        shutil.rmtree(logs, ignore_errors=True)
        print(f"removed {logs}")
    print("done")


if __name__ == "__main__":
    main()
