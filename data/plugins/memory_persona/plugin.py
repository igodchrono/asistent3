# -*- coding: utf-8 -*-
"""Совместимость: логика перенесена в plugins/memory.

Раньше memory_persona патчил PersistentMemory и дублировал факты.
Теперь единый плагин — «Память» (id=memory). Этот модуль оставлен,
чтобы старые настройки PLUGINS[memory_persona] не ломали загрузку.
"""
from __future__ import annotations

from core.plugin_api import AppContext, Plugin, SettingField


class PluginImpl(Plugin):
    id = "memory_persona"
    name = "Память (legacy → memory)"
    version = "2.0.0"
    description = "Объединено с plugins/memory. Можно выключить."
    settings_tab = "plugins"
    settings_tab_title = "memory_persona"
    settings_schema = [
        SettingField("enabled", "Включить (не нужно — используйте «Память»)", "bool", False),
    ]

    def on_load(self, app: AppContext) -> None:
        # не мешаем основному memory
        if app.get_plugin_setting(self.id, "enabled", False):
            print(
                "memory_persona: legacy включён, но логика в plugins/memory — "
                "рекомендуется выключить memory_persona в настройках",
                flush=True,
            )
        else:
            print("memory_persona: disabled (merged into memory)", flush=True)


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
