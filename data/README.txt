browser_search 4.2 — парсер + скачивание в чат
=============================================
Замени:
  data/plugins/browser_search/plugin.py
  data/plugins/browser_search/plugin.json
  data/core/chat_engine.py

Перезапусти ассистента.

Что умеет
---------
1) Поиск картинок («найди картинки арбуза»)
   — вкладка поиска как раньше
   — парсер: Openverse + Wikimedia + Bing + DuckDuckGo (не сетка Google)
   — список 1..N в чат
   — сразу качает 1-ю в data/attachments/ГГГГ-ММ-ДД/web_....jpg
     и вставляет в чат как [фото: ...]

2) «открой её» / «скачай 3» / «лучшую»
   — НЕ открывает Google заново
   — качает выбранный файл в чат

3) Поиск сайтов
   — DuckDuckGo HTML + Wikipedia (с кратким текстом)
   — «текст со 2» / «открой её» → текст страницы в чат + .txt

4) Прямая ссылка + «скачай»
   — jpg/png/webp, pdf, json, html-текст

Настройки вкладки «Браузер»
  Парсить выдачу — вкл
  После поиска картинок сразу 1-ю в чат — вкл
  Открывать вкладку поиска — по желанию

Лог ок:
  browser_search 4.2: parse + download to chat
  browser_search: parsed n=8 mode=images
  browser_search: saved image ... web_....jpg
