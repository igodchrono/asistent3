Эмоции — отдельный плагин, как персонажи
========================================

Не патч assistant_core под одну фичу.

Файлы скопировать так:

  D:\asistent\data\plugin_loader.py

  D:\asistent\data\plugins\emotion\plugin.json
  D:\asistent\data\plugins\emotion\plugin.py
  D:\asistent\data\plugins\emotion\__init__.py

В main.py ДО создания ассистента (один раз на все будущие паки):

    import plugin_loader
    plugin_loader.install()

Дальше новые плагины = новая папка data/plugins/<id>/ с plugin.py + plugin.json.
Ядро больше не трогаешь.

settings.json по желанию:
  "PLUGINS_DISABLED": []
  "PLUGINS_DIR": "plugins"

Выключить только эмоции: "PLUGINS_DISABLED": ["emotion"]
