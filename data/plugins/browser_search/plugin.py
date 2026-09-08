# -*- coding: utf-8 -*-
"""Tool: web_search / search_similar — нормализация query + открытие браузера."""
from __future__ import annotations

import re
import subprocess
import webbrowser
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from core.plugin_api import AppContext, HookResult, Plugin, SettingField


class PluginImpl(Plugin):
    id = "browser_search"
    name = "Браузер и поиск"
    version = "2.2.0"
    description = "Поиск в браузере с нормализацией запроса"
    settings_tab = "own"
    settings_tab_title = "Браузер"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField(
            "search_engine",
            "Поисковая система",
            "choice",
            "google",
            choices=["google", "yandex", "bing", "duckduckgo"],
        ),
        SettingField(
            "browser",
            "Браузер",
            "choice",
            "default",
            choices=["default", "chrome", "edge", "firefox", "opera", "brave"],
            help="default = системный браузер по умолчанию",
        ),
    ]

    def on_user_message(self, text, app):
        """Тонкий bridge для selftest / прямых фраз; основной путь — intent."""
        low = (text or "").strip().lower()
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        # явный поиск
        triggers = (
            "найди в интернете", "погугли", "загугли", "поищи в сети",
            "найди картин", "найди фото", "поиск картинок",
        )
        if any(t in low for t in triggers) or (
            (low.startswith("найди ") or low.startswith("поищи "))
            and not any(x in low for x in ("файл", "папк", "на диск"))
        ):
            mode = "images" if any(w in low for w in ("картин", "фото", "image", "обои")) else "web"
            if any(w in low for w in ("видео", "youtube", "ютуб")):
                mode = "video"
            q = self._normalize_query(text)
            if not q:
                q = text
            return HookResult(True, self.tool_web_search(app, query=q, mode=mode))
        return None

    def register_tools(self, app: AppContext) -> None:
        app.tools["web_search"] = self.tool_web_search
        app.tools["search_similar"] = self.tool_search_similar

    def tool_web_search(
        self, app: AppContext, query: str = "", mode: str = "web", **kwargs
    ) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return "SEARCH_FAIL reason=disabled"
        q = (query or kwargs.get("text") or "").strip()
        if not q:
            return "SEARCH_FAIL reason=empty_query"
        try:
            q = self._normalize_query(q) or q
        except Exception as e:
            print(f"browser_search: normalize skip: {e}", flush=True)
        mode = (mode or "web").lower()
        if mode not in ("web", "images", "video"):
            mode = self._guess_mode(query or q)
        url = self._url(q, mode, app)
        print(f"browser_search: open mode={mode} q={q!r} url={url[:120]}", flush=True)
        try:
            self._open(url, app)
        except Exception as e:
            return f"SEARCH_FAIL reason=open_error {e}"
        self._emotion(app, q)
        app.state["last_search_query"] = q
        app.state["last_search_mode"] = mode
        return f"SEARCH_OK mode={mode} query={q}"

    def tool_search_similar(
        self, app: AppContext, kind: str = "generic", **kwargs
    ) -> str:
        q = self._similar_query(app, kind)
        if not q:
            q = str(kwargs.get("query") or "").strip()
        if not q:
            return "SEARCH_FAIL reason=no_similar_context"
        mode = "images" if kind == "image" else "web"
        return self.tool_web_search(app, query=q, mode=mode)

    @staticmethod
    def _normalize_query(text: str) -> str:
        t = (text or "").strip()
        fluff = [
            r"^\s*(пожалуйста\s*[,:]?\s*)",
            r"^\s*(можешь|можете)\s+",
            r"^\s*(найди|найти|поищи|поискать|погугли|загугли|поиск)\s+",
            r"\b(в\s+интернете|в\s+гугле|в\s+google|в\s+сети|онлайн)\b",
            r"^\s*(мне|для\s+меня)\s+",
            r"^\s*(фотографию|фотография|фото|картинку|картинки|изображения|видео)\s+(по|про|с)?\s*",
        ]
        prev = None
        while prev != t:
            prev = t
            for p in fluff:
                t = re.sub(p, " ", t, flags=re.I)
            t = " ".join(t.split())
        return t.strip(" .,!?:;—-")

    def _similar_query(self, app: AppContext, kind: str) -> str:
        # приоритет: последний удачный поиск → keywords с экрана → файл
        val = str(app.state.get("last_search_query") or "")
        if not val:
            val = str(app.state.get("screen_vision_search_query") or "")
        if not val:
            val = str(app.state.get("pc_last_opened") or "")
        if not val:
            return ""
        val = val.replace("-", " ").replace("_", " ")
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
        low = (q or "").lower()
        if any(w in low for w in ("картин", "фото", "изображ", "image", "pics", "обои")):
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

    def _browser_exe(self, app: AppContext) -> Optional[str]:
        name = str(app.get_plugin_setting(self.id, "browser", "default") or "default").lower()
        if name in ("", "default", "system"):
            return None
        import os
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates = {
            "chrome": [
                rf"{pf}\Google\Chrome\Application\chrome.exe",
                rf"{pf86}\Google\Chrome\Application\chrome.exe",
                rf"{local}\Google\Chrome\Application\chrome.exe",
            ],
            "edge": [
                rf"{pf}\Microsoft\Edge\Application\msedge.exe",
                rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
            ],
            "firefox": [
                rf"{pf}\Mozilla Firefox\firefox.exe",
                rf"{pf86}\Mozilla Firefox\firefox.exe",
            ],
            "opera": [
                rf"{local}\Programs\Opera\opera.exe",
                rf"{pf}\Opera\opera.exe",
            ],
            "brave": [
                rf"{local}\BraveSoftware\Brave-Browser\Application\brave.exe",
                rf"{pf}\BraveSoftware\Brave-Browser\Application\brave.exe",
            ],
        }
        for p in candidates.get(name, []):
            if os.path.isfile(p):
                return p
        print(f"browser_search: exe not found for {name}, fallback default", flush=True)
        return None

    def _open(self, url: str, app: AppContext) -> None:
        exe = self._browser_exe(app)
        if exe:
            try:
                subprocess.Popen([exe, url], shell=False)
                print(f"browser_search: launched {exe}", flush=True)
                return
            except Exception as e:
                print(f"browser_search: exe fail: {e}", flush=True)
        try:
            if webbrowser.open(url):
                return
        except Exception as e:
            print(f"browser_search: webbrowser: {e}", flush=True)
        try:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
            return
        except Exception as e:
            print(f"browser_search: start: {e}", flush=True)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", f'Start-Process "{url}"'],
            shell=False,
        )

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
