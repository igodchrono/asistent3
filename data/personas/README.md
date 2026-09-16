# Персонажи

`characters/<id>/` — папка персонажа (`id` = имя папки).

Ядро:
- список и `ACTIVE_CHARACTER` в настройках
- хук: `on_character_changed(new_id, prev_id, app)`
- `app.get_active_character()`, `app.get_character_dir()`, `app.set_active_character(id)`

Карточка `.md` — личность для LLM. Команды (поиск, рисуй, ПК) разбирает `intents.py`, не карточка.

Плагин `persona` — эмоции и окно кадров (`images/`).
Плагин `memory` — `characters/<id>/memory/memory.db` (у каждого своя).
