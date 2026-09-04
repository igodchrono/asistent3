Плагин memory_persona
=====================

Куда:
  D:\asistent\data\plugin_loader.py          (если ещё нет)
  D:\asistent\data\plugins\memory_persona\plugin.py
  D:\asistent\data\plugins\memory_persona\plugin.json
  D:\asistent\data\plugins\memory_persona\__init__.py

В main.py ДО LMAssistant():
  import plugin_loader
  plugin_loader.install()

Что чинит
---------
1) После перезапуска факты есть во вкладке «Память», но модель их «не помнит».
   Причина: поиск шёл LIKE по зашифрованному полю. Теперь липкие факты
   (имя, запомни что…, профиль) всегда подмешиваются в промпт.

2) Смена персонажа: второй описывал внешность первого.
   Причина: кэш карточки + старые чанки RAG с карточкой №1.
   Теперь switch_character сбрасывает кэш и вычищает чужие карточки из RAG.

Смена персонажа: вкладка Персонаж → выбрать файл → Сохранить настройки.
Без «Сохранить» ядро не переключает карточку.