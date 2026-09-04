# -*- coding: utf-8 -*-
"""Пример: логирует смену персонажа. Можно удалить."""
from core.plugin_api import AppContext, Plugin

class PluginImpl(Plugin):
    id = "character_log"
    name = "Лог смены персонажа"
    version = "1.0.0"
    description = "Пишет в консоль on_character_changed (демо-хук)"
    settings_tab = "plugins"
    settings_schema = []

    def on_load(self, app: AppContext) -> None:
        print(f"character_log: active={app.get_active_character()} dir={app.get_character_dir()}", flush=True)

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        print(f"character_log: HOOK {previous_id} → {character_id} path={app.get_character_dir(character_id)}", flush=True)
