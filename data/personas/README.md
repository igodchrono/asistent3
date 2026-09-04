# Персонажи

`characters/<id>/` — папка персонажа.

Ядро:
- список и ACTIVE_CHARACTER в настройках
- хук плагинов: `on_character_changed(new_id, prev_id, app)`
- `app.get_active_character()`, `app.get_character_dir()`, `app.set_active_character(id)`

Плагины memory/avatar пишут в `characters/<id>/memory`, `avatar`, `plugin_data/`.
