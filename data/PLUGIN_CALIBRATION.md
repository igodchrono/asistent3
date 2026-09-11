# Калибровка плагинов (без встроенного браузера)

## Отключено
- browser_embed: enabled=False, не перехватывает поиск
- Поиск снова через системный браузер (Chrome/Edge/…)

## Приоритет on_user_message (чтобы не мешали друг другу)
1. pc_control — файлы/диск/открой путь
2. memory — запомни / забудь
3. notes / reminders
4. browser_search — только явный веб-поиск
5. Остальное → intent LLM

## Что стабилизировать по очереди
1. **browser_search** — refine запроса, без SEARCH_OK в чате, multi «и ещё»
2. **memory** — профиль в prompt, изоляция персонажей
3. **emotion + avatar** — [ANIM:] только для кадра, не в чате
4. **screen_vision / screen_react** — conf threshold, не спамить
5. **companion** — mood/time, proactivity cooldown
6. **pc_control** — не ловить «открой её»
7. **voice** — speak_enabled
8. **deep_think** — длинные ответы по фразам

## Настройки сейчас
Браузер → browser = default (не embed)
Встр. браузер → выкл

## Проверочные фразы
- найди картинки рыжих котов
- запомни: профиль: меня зовут …
- как меня зовут? (после рестарта)
- что на экране
- открой блокнот
- объясни подробно asyncio
