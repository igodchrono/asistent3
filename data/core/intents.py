# -*- coding: utf-8 -*-
"""Быстрые правила намерений. None = пусть решит LLM.

Запуск проверки: python intents.py  (из папки data/core или python -c)
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_TYPOS = (
    (r"\bнати\b", "найди"),
    (r"\bнайти\b", "найди"),
    (r"кортин", "картин"),
    (r"изображене", "изображение"),
    (r"девочь", "девоч"),
    (r"интерент", "интернет"),
    (r"гугол", "google"),
    (r"\bплз\b", "пожалуйста"),
    (r"пажалуста", "пожалуйста"),
    (r"симпотичн", "симпатичн"),
    (r"посмари", "посмотри"),
    (r"выбири", "выбери"),
)

_WEB_VERBS = (
    "найди в интернете", "поищи в интернете", "погугли", "загугли",
    "в гугле", "в google", "в яндексе", "найди в сети",
)
_IMG = ("картин", "фото", "изображ", "обои", "арт ", "art", "image", "wallpaper", "скрин")
_VID = ("видео", "youtube", "ютуб", "ролик", "клип")
_DISK = re.compile(
    r"(?:диск[аеу]?\s+[A-Za-z]\b|\b[A-Za-z]:(?:\\|/|\s|$)|в\s+проводнике|на\s+компьютере|локальн)",
    re.I,
)
_FILE_HINT = ("файл", "папк", "на диск", "на диске", "в папке", "на компьютере")


def normalize_text(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("ё", "е")
    for pat, repl in _TYPOS:
        t = re.sub(pat, repl, t, flags=re.I)
    t = re.sub(r"^\s*(так|ну|слушай|короче|эй|блин|типа)\s*[,:]?\s+", "", t, flags=re.I)
    return " ".join(t.split())


def _low(text: str) -> str:
    return normalize_text(text).lower()


def disk_letter(text: str) -> str:
    t = text or ""
    m = re.search(r"(?:диск[аеу]?\s+|на\s+диске\s+)([A-Za-z])\b", t, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([A-Za-z]):(?:\\|/|\s|$)", t)
    return m.group(1).upper() if m else ""


def is_local_search(low: str) -> bool:
    if _DISK.search(low):
        return True
    if any(w in low for w in ("найди файл", "найди папк", "открой файл", "открой папк")):
        return True
    if any(w in low for w in _FILE_HINT) and any(v in low for v in ("найди", "покажи", "открой")):
        return True
    return False


def is_new_similar(low: str) -> bool:
    return any(w in low for w in (
        "найди похож", "поищи похож", "найди такие", "поищи такие",
        "такие же но", "такие же, но", "еще такие", "ещё такие",
        "найди похожие", "покажи похож",
    ))


def is_pick(low: str, has_last_search: bool) -> bool:
    if is_new_similar(low):
        return False
    look = any(w in low for w in (
        "посмотри", "глянь", "посмотр", "на них", "на эти", "на картин",
        "на выдач", "на экран", "на монитор", "на результат", "повнимательн",
    ))
    pick = any(w in low for w in (
        "выбери", "выбрать", "самую", "самого", "лучш", "симпатичн",
        "какая лучше", "какой нравит", "какая нравит", "тебе нравит",
        "больше нравит", "какой мил", "какая мил", "похож",
    ))
    if look and pick:
        return True
    if has_last_search and (look or pick):
        return True
    return False


def is_describe_screen(low: str) -> bool:
    if any(w in low for w in ("на экране", "на мониторе", "на дисплее")):
        if any(w in low for w in ("что", "опиши", "покажи что")):
            return True
    return any(w in low for w in (
        "что я смотрю", "что открыто",
    ))


def is_web_search(low: str) -> bool:
    if is_local_search(low):
        return False
    if any(w in low for w in _WEB_VERBS):
        return True
    if any(w in low for w in ("погугли", "загугли")):
        return True
    if any(v in low for v in ("найди", "поищи", "покажи", "скинь")) and any(
        w in low for w in _IMG + _VID + ("в интернете", "в сети", "статью", "информац")
    ):
        return True
    if re.search(r"\b(курс\s+доллара|погода\s+(сегодня|завтра)|новости)\b", low):
        return True
    if re.search(r"\b(найди|поищи)\s+(что-?то|чего-?нибудь|интересн)", low):
        return True
    return False


def guess_mode(low: str) -> str:
    if any(w in low for w in _VID):
        return "video"
    if any(w in low for w in _IMG):
        return "images"
    return "web"


def strip_search_fluff(text: str) -> str:
    t = normalize_text(text)
    patterns = [
        r"^\s*(пожалуйста\s*[,:]?\s*)",
        r"^\s*(можешь\s+|можете\s+)",
        r"^\s*(найди|найти|поищи|поискать|погугли|загугли|поиск|поищу)\s+",
        r"^\s*(в\s+интернете|в\s+гугле|в\s+google|в\s+сети|онлайн)\s*",
        r"\s*(в\s+интернете|в\s+гугле|в\s+google|пожалуйста)\s*$",
        r"^\s*(мне\s+|для\s+меня\s+)",
        r"^\s*(картинки|картинку|фото|изображения|видео)\s+(по\s+|про\s+|с\s+)?",
        r"^\s*(как\s+найти)\s+",
        r"^\s*(покажи|скинь|хочу)\s+",
    ]
    prev = None
    while prev != t:
        prev = t
        for p in patterns:
            t = re.sub(p, " ", t, flags=re.I)
        t = " ".join(t.split())
    return t.strip(" .,!?:;—-")


def classify(text: str, ctx: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Уверенный intent или None (тогда LLM)."""
    ctx = ctx or {}
    raw = text or ""
    low = _low(raw)
    has_search = bool(ctx.get("last_search_query"))

    if not low:
        return {"intent": "chat", "args": {}, "speak": ""}

    if re.match(r"^(привет|хай|ку|здрасте|ты тут|ты здесь|ау)\b", low.rstrip("?!. ")):
        return {"intent": "chat", "args": {}, "speak": ""}

    if low in ("да", "давай", "ок", "окей", "yes", "ага", "угу", "хорошо", "го"):
        if ctx.get("pending_similar"):
            return {"intent": "search_similar", "args": {"kind": "generic"}, "speak": ""}
        if ctx.get("imggen_stage") in ("confirm", "drafting"):
            return None
        return {"intent": "chat", "args": {}, "speak": ""}

    if is_pick(low, has_search):
        return {"intent": "describe_screen", "args": {}, "speak": ""}
    if is_describe_screen(low):
        return {"intent": "describe_screen", "args": {}, "speak": ""}
    if is_new_similar(low):
        kind = "image" if any(w in low for w in _IMG) else "generic"
        return {"intent": "search_similar", "args": {"kind": kind}, "speak": ""}

    if any(w in low for w in (
        "открой ее", "открой её", "открой эту", "открой выбранн",
        "открой в другой вкладк", "открой в новой вкладк",
        "открой найден", "открой то что", "открой ту что",
        "открой картин", "открой ссылк", "открой первую", "открой этот",
    )):
        return {"intent": "open_last_search", "args": {}, "speak": ""}
    if has_search and (low.startswith("открой") or low.startswith("открыть") or low in ("открой", "открыть")):
        if not is_local_search(low) and not any(w in low for w in (
            "блокнот", "калькулятор", "проводник", "папк", "файл ",
            "chrome", "firefox", "explorer",
        )):
            return {"intent": "open_last_search", "args": {}, "speak": ""}

    if is_local_search(low):
        disk = disk_letter(raw) or disk_letter(low)
        if "папк" in low:
            q = strip_search_fluff(re.sub(r"папк[уие]\s*", " ", low, flags=re.I))
            q = re.sub(r"на\s+диске?\s+[a-z]\b", "", q, flags=re.I).strip()
            return {"intent": "pc_search_folders", "args": {"query": q or "folder", "disk": disk}, "speak": ""}
        q = strip_search_fluff(low)
        q = re.sub(r"на\s+диске?\s+[a-z]\b", "", q, flags=re.I).strip()
        if any(w in low for w in _IMG):
            q = q or "картинки"
        return {"intent": "pc_search_files", "args": {"query": q or "*", "disk": disk}, "speak": ""}

    if is_web_search(low):
        q = strip_search_fluff(raw)
        mode = guess_mode(low)
        if len(q) < 2:
            q = "интересное" if "интересн" in low else raw
        return {"intent": "web_search", "args": {"query": q, "mode": mode}, "speak": ""}

    if low.startswith("запомни"):
        body = raw.split(":", 1)[-1].strip() if ":" in raw else (raw.split(" ", 1)[-1] if " " in raw else "")
        return {"intent": "memory_add", "args": {"text": body}, "speak": ""}
    if any(w in low for w in ("что ты помнишь", "что помнишь", "покажи память")):
        return {"intent": "memory_list", "args": {}, "speak": ""}
    if low.startswith("забудь"):
        body = raw.split(" ", 1)[-1] if " " in raw else ""
        return {"intent": "memory_forget", "args": {"text": body}, "speak": ""}

    if low.startswith("напомни"):
        return {"intent": "reminder_add", "args": {"text": raw}, "speak": ""}
    if "список напоминаний" in low or low == "напоминания":
        return {"intent": "reminder_list", "args": {}, "speak": ""}

    if "покажи заметк" in low or low in ("заметки", "покажи заметки"):
        return {"intent": "note_list", "args": {}, "speak": ""}
    if low.startswith("запиши") or low.startswith("заметка"):
        body = raw.split(":", 1)[-1].strip() if ":" in raw else (raw.split(" ", 1)[-1] if " " in raw else raw)
        return {"intent": "note_add", "args": {"text": body}, "speak": ""}

    if low.startswith("открой ") or low.startswith("открыть "):
        tgt = low.split(" ", 1)[-1].strip(" .!?")
        if tgt in ("блокнот", "калькулятор", "notepad", "calc", "calculator"):
            return {"intent": "pc_open", "args": {"target": tgt}, "speak": ""}
        if tgt in ("chrome", "firefox", "проводник", "explorer"):
            return {"intent": "pc_open", "args": {"target": tgt}, "speak": ""}

    if low.startswith("закрой ") or low.startswith("закрыть "):
        tgt = low.split(" ", 1)[-1].strip(" .!?")
        if "последн" in tgt:
            return {"intent": "pc_close_last", "args": {}, "speak": ""}
        if tgt:
            return {"intent": "pc_close", "args": {"target": tgt}, "speak": ""}

    if low in ("громче", "сделай громче"):
        return {"intent": "pc_volume", "args": {"direction": "up"}, "speak": ""}
    if low in ("тише", "сделай тише"):
        return {"intent": "pc_volume", "args": {"direction": "down"}, "speak": ""}

    if "очисти корзину" in low or "очистить корзину" in low:
        return {"intent": "pc_empty_recycle", "args": {}, "speak": ""}
    if "создай текстовый файл" in low or low.startswith("создай файл"):
        name = raw.split("файл", 1)[-1].strip() if "файл" in low else "note.txt"
        return {"intent": "pc_create_text", "args": {"name": name}, "speak": ""}

    if any(w in low for w in ("подробно", "максимально точно", "разбери подробно")) and len(low) > 12:
        return {"intent": "deep_think", "args": {}, "speak": ""}

    if any(w in low for w in ("что такое", "объясни", "напиши код", "кусок кода", "как сделать функцию")):
        return {"intent": "chat", "args": {}, "speak": ""}

    return None


if __name__ == "__main__":
    CASES = [
        ("ты тут?", "chat", {}),
        ("напиши кусок кода для плеера браузера", "chat", {}),
        ("что такое asyncio", "chat", {}),
        ("объясни подробно что такое список", "deep_think", {}),
        ("найди картинку аниме девочки акулы", "web_search", {}),
        ("так найди картинку аниме девочки акулы", "web_search", {}),
        ("нати кортинку акулы", "web_search", {}),
        ("покажи картинки кошек", "web_search", {}),
        ("погугли курс доллара", "web_search", {}),
        ("найди в интернете как настроить asyncio", "web_search", {}),
        ("найди видео про лис", "web_search", {}),
        ("найди картинки на диске E", "pc_search_files", {}),
        ("найди файл readme на диске D", "pc_search_files", {}),
        ("найди папку asistent", "pc_search_folders", {}),
        ("посмотри на них и выбери самую похожую", "describe_screen", {"last_search_query": "акула"}),
        ("какая тебе больше нравится", "describe_screen", {"last_search_query": "акула"}),
        ("выбери лучшую", "describe_screen", {"last_search_query": "акула"}),
        ("что у меня сейчас на экране", "describe_screen", {}),
        ("посмотри повнимательней на средний монитор", "describe_screen", {"last_search_query": "акула"}),
        ("найди похожие изображения", "search_similar", {"last_search_query": "акула"}),
        ("такие же но лисичек", "search_similar", {"last_search_query": "акула"}),
        ("открой её", "open_last_search", {"last_search_query": "акула"}),
        ("открой в другой вкладке", "open_last_search", {"last_search_query": "акула"}),
        ("открой найденное", "open_last_search", {"last_search_query": "акула"}),
        ("открой выбранную", "open_last_search", {"last_search_query": "акула"}),
        ("открой", "open_last_search", {"last_search_query": "акула"}),
        ("запомни меня зовут Иван", "memory_add", {}),
        ("что ты помнишь", "memory_list", {}),
        ("забудь про чай", "memory_forget", {}),
        ("напомни через час про чай", "reminder_add", {}),
        ("запиши: купить молоко", "note_add", {}),
        ("громче", "pc_volume", {}),
        ("открой блокнот", "pc_open", {}),
        ("закрой калькулятор", "pc_close", {}),
        ("мне скучно", None, {}),
        ("найди что-то интересное", "web_search", {}),
    ]
    fail = 0
    for phrase, expect, ctx in CASES:
        got = classify(phrase, ctx)
        intent = None if got is None else got.get("intent")
        if expect is None:
            ok = got is None or intent == "chat"
        else:
            ok = intent == expect
        if not ok:
            fail += 1
        extra = ""
        if got and got.get("args"):
            extra = " " + str(got["args"])
        print(f"  {'OK ' if ok else 'FAIL'} [{expect}] {phrase!r} → {intent}{extra}")
    print(f"fail={fail}/{len(CASES)}")
    raise SystemExit(fail)
