# -*- coding: utf-8 -*-
"""Только window.py для совместимости. Логика в persona."""
from core.plugin_api import AppContext, Plugin
class PluginImpl(Plugin):
    id = "avatar"
    name = "Аватар (window helper)"
    version = "0.1.0"
    def on_load(self, app: AppContext) -> None:
        print("🖼 avatar helper: window.py на месте, кадры ведёт persona", flush=True)
def register():
    return PluginImpl()
