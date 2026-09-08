# -*- coding: utf-8 -*-
"""Tool: web_search / search_similar — без regex на фразы пользователя."""
from __future__ import annotations

import re
import subprocess
import webbrowser
from typing import Any, Optional
from urllib.parse import quote_plus

from core.plugin_api import AppContext, Plugin, SettingField


class PluginImpl(Plugin):
    id = "browser_search"
    name = "Браузер и поиск"
    version = "2.0.0"
    description = "Исполнитель поиска (intent → web_search / search_similar)."
    settings_tab = "own"
    settings_tab_title = "Браузер"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("search_engine", "Поисковик", "choice", "google",
                     choices=["google", "yandex", "bing", "duckduckgo"]),
        SettingField("open_browser", "Открывать браузер", "bool", True),
    ]

    def on_load(self, app: AppContext) -> None:
        app.state["browser_search_plugin"] = self

    def on_user_message(self, text, app):
        from core.plugin_api import HookResult
        low = (text or "").strip().lower()
        for pref in ("найди в интернете ", "поищи в интернете ", "найди картинки ", "найди ", "поищи "):
            if low.startswith(pref):
                q = text[len(pref):].strip()
                if any(x in low for x in ("похож", "similar")):
                    return HookResult(True, self.tool_search_similar(app, kind="generic"))
                mode = "images" if "картин" in low else "web"
                return HookResult(True, self.tool_web_search(app, query=q, mode=mode))
        return None

    def register_tools(self, app: AppContext) -> None:
        app.tools["web_search"] = self.tool_web_search
        app.tools["search_similar"] = self.tool_search_similar

    def tool_web_search(self, app: AppContext, query: str = "", mode: str = "web", **kwargs) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return "Поиск отключён в настройках."
        q = (query or kwargs.get("text") or "").strip()
        if not q:
            return "Не указан запрос для поиска."
        mode = (mode or "web").lower()
        if mode not in ("web", "images", "video"):
            mode = self._guess_mode(q)
        url = self._url(q, mode, app)
        if app.get_plugin_setting(self.id, "open_browser", True):
            self._open(url, app)
        label = {"web": "поиск", "images": "поиск картинок", "video": "поиск видео"}[mode]
        self._emotion(app, q)
        return f"Открыт {label}: {q}"

    def tool_search_similar(self, app: AppContext, kind: str = "generic", **kwargs) -> str:
        kind = (kind or "generic").lower()
        q = self._context_query(app)
        if not q:
            return (
                "Не из чего искать похожее. Сначала спроси «что на экране» "
                "или открой файл — потом «найди похожее»."
            )
        mode = "images" if kind in ("image", "images", "picture", "картинка") else "web"
        if kind in ("site", "sites", "сайт"):
            mode = "web"
        return self.tool_web_search(app, query=q, mode=mode)

    def _context_query(self, app: AppContext) -> str:
        for key in (
            "screen_vision_search_query",
            "screen_vision_last_desc",
            "pc_last_opened",
            "pc_last_found",
            "screen_react_title",
        ):
            val = str(app.state.get(key) or "").strip()
            if not val:
                continue
            # имя файла
            if "\\" in val or "/" in val:
                from pathlib import Path
                p = Path(val)
                if p.suffix:
                    val = p.stem.replace("-", " ").replace("_", " ")
            words = []
            stop = {
                "монитор", "экран", "chrome", "google", "вижу", "хозяин", "окно",
                "строка", "ввода", "слева", "справа", "панель", "задач", "windows",
            }
            for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", val):
                lw = w.lower()
                if lw not in stop and lw not in words:
                    words.append(lw)
                if len(words) >= 8:
                    break
            if words:
                app.state["screen_vision_pending_similar"] = False
                return " ".join(words)
        return ""

    @staticmethod
    def _guess_mode(q: str) -> str:
        low = q.lower()
        if any(w in low for w in ("картин", "фото", "изображ", "image", "pics")):
            return "images"
        if any(w in low for w in ("видео", "youtube", "ютуб")):
            return "video"
        return "web"

    def _url(self, query: str, mode: str, app: AppContext) -> str:
        engine = str(app.get_plugin_setting(self.id, "search_engine", "google") or "google").lower()
        enc = quote_plus(query)
        if mode == "images":
            if engine == "yandex":
                return f"https://yandex.ru/images/search?text={enc}"
            if engine == "bing":
                return f"https://www.bing.com/images/search?q={enc}"
            return f"https://www.google.com/search?tbm=isch&q={enc}"
        if mode == "video":
            return f"https://www.youtube.com/results?search_query={enc}"
        if engine == "yandex":
            return f"https://yandex.ru/search/?text={enc}"
        if engine == "bing":
            return f"https://www.bing.com/search?q={enc}"
        if engine == "duckduckgo":
            return f"https://duckduckgo.com/?q={enc}"
        return f"https://www.google.com/search?q={enc}"

    def _open(self, url: str, app: AppContext) -> None:
        try:
            webbrowser.open(url)
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)

    def _emotion(self, app: AppContext, q: str) -> None:
        emo = "flirty" if any(w in q.lower() for w in ("18+", "hentai", "хентай", "nsfw")) else "searching"
        pl = app.plugins.get("emotion")
        if pl and hasattr(pl, "set_context"):
            try:
                pl.set_context(app, emo, "web_search")
            except Exception:
                pass


def register():
    return PluginImpl()
