# -*- coding: utf-8 -*-
"""Только window.py для импорта. Кадры ведёт persona. Не занимает ключ avatar."""
from core.plugin_api import AppContext, Plugin
class PluginImpl(Plugin):
    id = "avatar_stub"
    name = "Аватар (window helper)"
    version = "0.1.0"
    def on_load(self, app: AppContext) -> None:
        print("🖼 avatar helper: window.py на месте, кадры ведёт persona", flush=True)
def register():
    return PluginImpl()
