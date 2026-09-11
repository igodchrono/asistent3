# -*- coding: utf-8 -*-
"""Заглушка: логика переехала в плагин persona."""
from core.plugin_api import AppContext, Plugin

class PluginImpl(Plugin):
    id = "emotion"
    name = "Эмоции (stub → persona)"
    version = "0.0.0"
    description = "Отключён: используй persona"

    def on_load(self, app: AppContext) -> None:
        if "persona" in app.plugins:
            print("🧠 emotion stub: persona активен, этот плагин молчит", flush=True)
            return
        print("🧠 emotion stub: поставь plugins/persona", flush=True)

def register():
    return PluginImpl()
