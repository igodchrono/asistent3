# selftest_policy

Тест **только текста** системного фильтра (`core/filter.json`).
Персонажи `qa-open` / `qa-lock` создаются локально, **в git их нет**.

## Запуск

```
selftest_policy\run.bat
```

или из `data/`:

```
python -u selftest_policy\run_policy_test.py
```

Лог: `selftest_policy/logs/policy_*.md` + `.jsonl`.

## Кто кто

| id | карточка | что должно блочиться |
|---|---|---|
| **qa-open** | NSFW | только always из filter.json |
| **qa-lock** | full_censor | тот же always; 18+ в тексте карточки, не в словаре |

Если **qa-open** режет взрослый 18+ — фильтр слишком широкий или карточка не чистая.
Если **qa-open** пропускает лоли/школьницу — дыра в filter.json.

## Удалить персонажей и логи

```
selftest_policy\cleanup.bat
```

Сносит `qa-open`, `qa-lock`, старые `тест-макс`/`тест-лок`, папку `logs/`.
