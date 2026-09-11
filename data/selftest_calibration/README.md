# selftest_calibration

Отдельная папка с автопроверкой плагинов. **Можно удалить целиком.**

## Запуск

Из `data/`:

```bat
selftest_calibrationun_calibration.bat
```

С LLM и браузером:

```bat
selftest_calibrationun_calibration_full.bat
```

или:

```bat
..\python\python.exe -u selftest_calibration\run_calibration.py --llm --browser
```

Опции:
- `--llm` — короткий запрос к LM Studio
- `--browser` — реальный поиск в браузере
- `--pc` — открыть notepad

## Что проверяет (по порядку)

0. Загрузка плагинов, embed OFF  
1. browser_search (normalize, split, open)  
2. memory add/list  
3. strip [ANIM:]  
4. pc_control (не ловит «открой её»)  
5. screen  
6. companion time  
7. deep_think  
8. LLM optional  

Лог: `data/selftest_calibration_run.log`

## Удаление

```bat
rmdir /s /q data\selftest_calibration
del data\selftest_calibration_run.log
```
