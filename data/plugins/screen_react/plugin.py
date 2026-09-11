# -*- coding: utf-8 -*-
from core.plugin_api import AppContext, Plugin
class PluginImpl(Plugin):
    id = "screen_react"
    name = "Реакция на экран (stub → screen)"
    version = "0.0.0"
    def on_load(self, app: AppContext) -> None:
        print("👁 screen_react stub: используй плагин screen", flush=True)
def register():
    return PluginImpl()
