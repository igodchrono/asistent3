asistent3 — полный пакет недостающих функций из asistent2
=========================================================

Содержимое
----------
emotion_analyzer.py              → data/  (полный анализатор v2 + NSFW)
persistent_memory.py             → data/  (долговременная память, crypto опционально)
models/intent_model/micro_models.py → data/models/intent_model/
plugins/emotion/                 → полный analyzer + map + аватар
plugins/screen_react/            → SCENE_TO_ANIM / OCR cache / заголовок окна
plugins/memory_persona/          → PersistentMemory в промпт + авто-факты
plugins/reminders/               → «напомни через 5 минут …»
plugins/notes/                   → «запиши: …» / notes.md
plugins/rag/                     → keyword-RAG по .md/.txt персонажа
personas/characters/_template/emotions_map.json

Установка (Windows)
-------------------
DATA = D:\asistent\asistent\asistent3\data

1) Останови ассистента.

2) Скопируй в DATA:
   emotion_analyzer.py
   persistent_memory.py
   models\intent_model\micro_models.py

3) Скопируй папки плагинов:
   plugins\emotion\
   plugins\screen_react\
   plugins\memory_persona\
   plugins\reminders\
   plugins\notes\
   plugins\rag\

4) (опционально) emotions_map.json в personas\characters\лисичка\

5) Запусти. В логе ожидай:
   🧠 emotion: EmotionalAnalyzer loaded
   👁 screen_react: loaded
   🧠 memory_persona: PersistentMemory → ...
   ⏰ reminders: ...
   📝 notes: ...
   📚 rag: indexed chunks=...

Как пользоваться
----------------
Эмоции:
  «люблю тебя» / эмодзи / NSFW-фразы → кадр аватара
  Правка: personas/characters/<id>/emotions_map.json

Экран:
  Каждые N сек (настройки «Реакция на экран») + «что на экране»
  SCENE_TO_ANIM: cats→happy, code→thinking, game→playful, error→shocked…

Память:
  «меня зовут Иван» / «запомни: …» → в SQLite и в промпт после рестарта

Напоминания:
  «напомни через 5 минут проверить чай»
  «список напоминаний» / «отмени напоминание #3»

Заметки:
  «запиши: купить молоко»
  «покажи заметки» / «найди в заметках молоко»

RAG:
  Клади .md/.txt в папку персонажа → при старте индекс
  При вопросе релевантные куски попадут в system prompt

Зависимости
-----------
Опционально: pip install cryptography   (шифрование памяти)
Pillow / mss уже для screen_vision
PyQt5 — таймеры screen_react / reminders
EOF
