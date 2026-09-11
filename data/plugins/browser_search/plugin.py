# -*- coding: utf-8 -*-
"""Браузерный поиск: multi-query, normalize, open tabs."""
from __future__ import annotations

import re
import subprocess
import webbrowser
from typing import Any, List, Optional
from urllib.parse import quote_plus

from core.plugin_api import AppContext, HookResult, Plugin, SettingField


class PluginImpl(Plugin):
    id = "browser_search"
    name = "Браузер и поиск"
    version = "3.1.0"
    description = "Поиск в браузере, несколько вкладок"
    settings_tab = "own"
    settings_tab_title = "Браузер"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField(
            "search_engine", "Поисковая система", "choice", "google",
            choices=["google", "yandex", "bing", "duckduckgo"],
        ),
        SettingField(
            "open_each_query",
            "Несколько запросов → несколько вкладок",
            "bool",
            True,
        ),
        SettingField(
            "browser", "Браузер", "choice", "default",
            choices=["default", "embed", "chrome", "edge", "firefox", "opera", "brave"],
        ),
    ]

    def on_user_message(self, text, app):
        if app.state.get("ero_game"):
            return None  # режим эро-игры — фото-чат, не браузер
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        if hasattr(app, "is_plugin_enabled") and not app.is_plugin_enabled(self.id):
            return None
        low = (text or "").strip().lower()
        # «открой её / в другой вкладке» после поиска картинок
        if low.startswith("открой") or low.startswith("открыть"):
            if any(w in low for w in ("ее", "её", "эту", "картин", "ссылк", "вкладк", "лучш")):
                if app.state.get("last_search_query") or app.state.get("last_search_url"):
                    return HookResult(True, self.tool_open_last(app, text=text))
        if any(x in low for x in ("файл", "папк", "на диск", "на диске", "в проводнике")):
            return None
        explicit = (
            "найди в интернете", "поищи в интернете", "поищи в сети",
            "погугли", "загугли", "в гугле",
            "найди картинки", "найди картинку", "найди фото", "поиск картинок",
            "найди на youtube", "найди видео",
        )
        if not any(t in low for t in explicit):
            return None
        mode = self._guess_mode(text)
        q = self._normalize_query(text)
        return HookResult(True, self.tool_web_search(app, query=q or text, mode=mode))

    def register_tools(self, app: AppContext) -> None:
        app.tools["web_search"] = self.tool_web_search
        app.tools["search_similar"] = self.tool_search_similar
        app.tools["open_last_search"] = self.tool_open_last


    def _use_embed(self, app: AppContext) -> bool:
        """Встроенный браузер только если явно выбран embed И плагин включён."""
        emb = app.plugins.get("browser_embed")
        if emb is None:
            return False
        if not app.get_plugin_setting("browser_embed", "enabled", False):
            return False
        name = str(app.get_plugin_setting(self.id, "browser", "default") or "default").lower().strip()
        return name in ("embed", "lisichka", "лисичка", "встроенный", "internal")


    def tool_web_search(
        self, app: AppContext, query: str = "", mode: str = "web", **kwargs
    ) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return "SEARCH_FAIL reason=disabled"
        if hasattr(app, "is_plugin_enabled") and not app.is_plugin_enabled(self.id):
            return "SEARCH_FAIL reason=disabled"
        if app.state.get("ero_game"):
            pm = app.plugins.get("phone_media")
            if pm and hasattr(pm, "tool_send_photo"):
                print("browser_search: ero_game → phone_media", flush=True)
                return pm.tool_send_photo(app, query=query or kwargs.get("text") or "")
            return "Сначала игра ловит фото. Скажи: пришли фото."

        mode = (mode or "web").lower()
        queries = kwargs.get("queries") or []
        if isinstance(queries, str):
            queries = [queries]
        queries = [str(x).strip() for x in queries if str(x).strip()]
        if not queries:
            q0 = (query or kwargs.get("text") or "").strip()
            if q0:
                queries = self._split_user_queries(q0)
        if not queries:
            return "SEARCH_FAIL reason=empty_query"

        norm = []
        for q in queries:
            n = self._normalize_query(q) or q
            n = (n or q).strip()
            if n:
                norm.append(n)
        queries = norm or queries

        if mode not in ("web", "images", "video"):
            mode = self._guess_mode(queries[0])

        multi = bool(app.get_plugin_setting(self.id, "open_each_query", True))
        to_open = queries if (multi and len(queries) > 1) else [queries[0]]

        if self._use_embed(app):
            emb = app.plugins.get("browser_embed")
            if emb and hasattr(emb, "tool_search"):
                last = "SEARCH_FAIL"
                use_q = queries if (bool(app.get_plugin_setting(self.id, "open_each_query", True)) and len(queries) > 1) else [queries[0]]
                for q in use_q:
                    print(f"browser_search: → embed search q={q!r} mode={mode}", flush=True)
                    last = emb.tool_search(app, query=q, mode=mode)
                return last
            print("browser_search: embed выбран, плагин browser_embed не найден", flush=True)
        opened = []
        for q in to_open:
            url = self._url(q, mode, app)
            print(f"browser_search: open mode={mode} q={q!r} url={url[:120]}", flush=True)
            try:
                self._open(url, app)
                opened.append(q)
            except Exception as e:
                print(f"browser_search: open fail {e}", flush=True)
        if not opened:
            return "SEARCH_FAIL reason=open_error"

        self._emotion(app, opened[0])
        app.state["last_search_query"] = opened[0]
        app.state["last_search_queries"] = opened
        app.state["last_search_mode"] = mode
        try:
            app.state["last_search_url"] = self._url(opened[0], mode, app)
        except Exception:
            pass
        if opened:
            try:
                app.state["last_search_url"] = self._url(opened[0], mode, app)
            except Exception:
                pass
        if len(opened) == 1:
            return f"SEARCH_OK mode={mode} query={opened[0]}"
        return f"SEARCH_OK mode={mode} queries={opened}"

    def tool_search_similar(self, app: AppContext, kind: str = "generic", **kwargs) -> str:
        if app.state.get("ero_game"):
            pm = app.plugins.get("phone_media")
            if pm and hasattr(pm, "tool_send_photo"):
                print("browser_search: similar → phone_media", flush=True)
                return pm.tool_send_photo(app, query=str(kwargs.get("query") or "photo"))
        q = self._similar_query(app, kind)
        if not q:
            q = str(kwargs.get("query") or "").strip()
        if not q:
            return "SEARCH_FAIL reason=no_similar_context"
        mode = "images" if kind in ("image", "images") else "web"
        return self.tool_web_search(app, query=q, mode=mode)

    def tool_open_last(self, app: AppContext, text: str = "", **kwargs) -> str:
        if self._use_embed(app):
            emb = app.plugins.get("browser_embed")
            if emb and hasattr(emb, "tool_open_last"):
                return emb.tool_open_last(app, text=text, **kwargs)
        """Открыть последнюю ВЫДАЧУ поиска, не текст ответа ассистента."""
        q = str(app.state.get("last_search_query") or "").strip()
        mode = str(app.state.get("last_search_mode") or "images")
        url = str(app.state.get("last_search_url") or "").strip()
        low = (text or "").lower()

        # Игнорируем прозу чата в last_image_pick
        pick = str(app.state.get("last_image_pick") or "").strip()
        if pick and self._is_sane_query(pick):
            if q and pick.lower() not in q.lower():
                q_try = (q + " " + pick).strip()
            else:
                q_try = pick
            if self._is_sane_query(q_try):
                q = q_try
                url = ""

        if not q and not url:
            return "Нет последнего поиска картинок. Сначала найди изображения."

        if url and not (pick and self._is_sane_query(pick)):
            # предпочтительно та же выдача
            pass
        elif not url:
            if not self._is_sane_query(q):
                q = str(app.state.get("last_search_query") or "").strip()
            if not q:
                return "Нечего открыть."
            mode = mode if mode in ("web", "images", "video") else "images"
            url = self._url(q, mode, app)

        # если url был от прозы — пересобрать
        if not self._is_sane_query(q) and app.state.get("last_search_query"):
            q = str(app.state.get("last_search_query")).strip()
            mode = str(app.state.get("last_search_mode") or "images")
            url = self._url(q, mode if mode in ("web", "images", "video") else "images", app)

        print(f"browser_search: open_last q={q!r} url={url[:140]}", flush=True)
        try:
            self._open(url, app)
        except Exception as e:
            return f"Не удалось открыть вкладку: {e}"
        app.state["last_search_url"] = url
        if "вкладк" in low:
            return f"Открыла вкладку с выдачей: {q}"
        return f"Открыла выдачу поиска: {q}"

    @staticmethod
    def _is_sane_query(q: str) -> bool:
        q = (q or "").strip()
        if len(q) < 2 or len(q) > 80:
            return False
        low = q.lower()
        for b in (
            "хозяин", "эй,", "фрр", "нравится", "могу ещё", "могу еще",
            "search_ok", "anim:", "вот эта", "для тебя",
        ):
            if b in low:
                return False
        if q.count(".") + q.count("!") + q.count("?") > 1:
            return False
        if q.count(",") > 2:
            return False
        return True


    @staticmethod
    def _split_user_queries(text: str) -> list:
        raw = (text or "").strip()
        if not raw:
            return []
        parts = re.split(
            r"\s+(?:и\s+ещ[её]|и\s+также|а\s+также|и\s+потом)\s+",
            raw,
            flags=re.I,
        )
        if len(parts) < 2:
            parts = re.split(r"\s+и\s+(?=найди|найти|поищи|погугли|картин)", raw, flags=re.I)
        out: List[str] = []
        for p in parts:
            p = re.sub(r"^(найди|найти|поищи|погугли|загугли)\s+", "", p.strip(), flags=re.I)
            p = re.sub(r"^(картинки|картинку|фото|изображения)\s+", "", p, flags=re.I)
            p = " ".join(p.split()).strip(" .,;:")
            if len(p) >= 2:
                out.append(p)
        return out or [raw]

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
            r"^\s*(что-?то|чего-?то|что\s+нибудь)\s+",
        ]
        prev = None
        while prev != t:
            prev = t
            for p in fluff:
                t = re.sub(p, " ", t, flags=re.I)
            t = " ".join(t.split())
        return t.strip(" .,!?:;—-")

    def _similar_query(self, app: AppContext, kind: str) -> str:
        val = str(app.state.get("last_search_query") or "").strip()
        if not val:
            raw = str(app.state.get("screen_vision_search_query") or "").strip()
            junk = ("день", "вечер", "утро", "лови", "ищу", "жми")
            if raw and not any(j in raw.lower() for j in junk):
                val = raw
        if not val:
            return ""
        words = []
        stop = {"монитор", "экран", "chrome", "google", "вижу", "хозяин", "окно"}
        for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", val):
            lw = w.lower()
            if lw not in stop and lw not in words:
                words.append(w)
            if len(words) >= 8:
                break
        return " ".join(words)

    @staticmethod
    def _guess_mode(q: str) -> str:
        low = (q or "").lower()
        if any(w in low for w in ("картин", "фото", "изображ", "image", "обои")):
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
        import os
        name = str(app.get_plugin_setting(self.id, "browser", "default") or "default").lower()
        if name in ("", "default", "system"):
            return None
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates = {
            "chrome": [
                rf"{pf}\Google\Chrome\Application\chrome.exe",
                rf"{local}\Google\Chrome\Application\chrome.exe",
            ],
            "edge": [rf"{pf}\Microsoft\Edge\Application\msedge.exe"],
            "firefox": [rf"{pf}\Mozilla Firefox\firefox.exe"],
            "opera": [rf"{local}\Programs\Opera\opera.exe"],
            "brave": [rf"{local}\BraveSoftware\Brave-Browser\Application\brave.exe"],
        }
        for p in candidates.get(name, []):
            if os.path.isfile(p):
                return p
        return None

    def _open(self, url: str, app: AppContext) -> None:
        if self._use_embed(app):
            emb = app.plugins.get("browser_embed")
            if emb and hasattr(emb, "tool_open"):
                print(f"browser_search: → embed open {url[:100]}", flush=True)
                emb.tool_open(app, url=url)
                return
        exe = self._browser_exe(app)
        if exe:
            subprocess.Popen([exe, url], shell=False)
            return
        try:
            if webbrowser.open(url):
                return
        except Exception as e:
            print(f"browser_search: webbrowser: {e}", flush=True)
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
