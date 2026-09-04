Плагин emotion
==============

Куда:
  D:\asistent\data\plugins\emotion\
    plugin.json
    plugin.py
    __init__.py
    README.txt

И загрузчик (один на все паки):
  D:\asistent\data\plugin_loader.py

В main.py — одна строка на ВСЕ плагины, не на эмоции:

  import plugin_loader
  plugin_loader.install()

Ставить ДО `assistant = LMAssistant()`.

Выключить пак:
  settings.json → "PLUGINS_DISABLED": ["emotion"]
  или в plugin.json "enabled": false

Ядро (assistant_core) под эмоции не правится.
Плагин вешается на AnimationSelector.select и ContextManager.get_mood_prompt_addon.
Анализатор — тот же emotion_service, второй HybridAnalyzer не создаётся.
