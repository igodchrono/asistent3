# -*- coding: utf-8 -*-
"""Заглушка: логика в plugins/persona. Не занимает ключ emotion."""
from core.plugin_api import AppContext, Plugin

class PluginImpl(Plugin):
    id = "emotion_stub"
    name = "Эмоции (stub → persona)"
    version = "0.0.0"
    description = "Отключён: используй persona"

    def on_load(self, app: AppContext) -> None:
        print("🧠 emotion stub: логика в persona, этот пак не регистрируется как emotion", flush=True)

def register():
    return PluginImpl()
