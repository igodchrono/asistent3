# -*- coding: utf-8 -*-
"""
Companion — этапы 1–3 «живого помощника»:
  1) время + mood + профиль в каждом LLM-запросе
  2) сцена экрана (code/movie/nsfw/writing/browsing/idle) + реакция
  3) паттерны пользователя + редкие предложения (cooldown)
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_SCENE_HINTS = {
    "coding": (
        "code", "visual studio", "vscode", "pycharm", "idea", "cursor", "sublime",
        "terminal", "cmd.exe", "powershell", "windows terminal", "git", "docker",
        "stackoverflow", "github", ".py", "debug",
    ),
    "writing": (
        "word", "docs", "notepad", "блокнот", "obsidian", "notion", "typora",
        "writer", "google docs", "libreoffice",
    ),
    "movie": (
        "youtube", "netflix", "kino", "кино", "vlc", "mpv", "potplayer", "plex",
        "prime video", "ivI", "фильм", "сериал", "twitch",
    ),
    "nsfw": (
        "porno", "porn", "xvideos", "xnxx", "hentai", "18+", "nhentai", "rule34",
        "xxx", "sex", "nsfw",
    ),
    "browsing": (
        "chrome", "firefox", "edge", "opera", "brave", "yandex", "mozilla",
    ),
    "chat": (
        "telegram", "discord", "whatsapp", "slack", "teams", "zoom",
    ),
}


class PluginImpl(Plugin):
    id = "companion"
    name = "Живой компаньон"
    version = "1.0.0"
    description = "Время, настроение, профиль, сцены экрана, паттерны"
    settings_tab = "own"
    settings_tab_title = "Компаньон"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("scene_interval_sec", "Проверка экрана (сек)", "int", 45, min_value=15, max_value=300),
        SettingField("suggest_cooldown_min", "Пауза между предложениями (мин)", "int", 12, min_value=3, max_value=120),
        SettingField("suggest_chance", "Шанс предложения %", "int", 35, min_value=0, max_value=100),
        SettingField("mood_drift", "Смена настроения со временем", "bool", True),
        SettingField("proactive", "Проактивные реплики по сцене", "bool", True),
    ]

    def __init__(self) -> None:
        self._timer = None
        self._last_suggest_at = 0.0
        self._last_scene = "idle"
        self._last_scene_at = 0.0
        self._patterns: Dict[str, int] = {}
        self.app: Optional[AppContext] = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        self._load_patterns(app)
        self._ensure_mood(app)
        self._tick_time(app)
        try:
            from PyQt5 import QtCore
            self._timer = QtCore.QTimer()
            sec = int(app.get_plugin_setting(self.id, "scene_interval_sec", 45) or 45)
            self._timer.setInterval(max(15, sec) * 1000)
            self._timer.timeout.connect(lambda: self._on_tick(app))
            self._timer.start()
        except Exception as e:
            print(f"companion: timer {e}", flush=True)
        print("🧠 companion 1.0: time+mood+scene+patterns", flush=True)

    def on_shutdown(self, app: AppContext) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
        self._save_patterns(app)

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        # настроение сбрасываем мягко при смене персонажа
        app.state["companion_mood"] = "curious"
        app.state["companion_mood_energy"] = 0.6
        self._load_patterns(app)

    def on_user_message(self, text: str, app: AppContext):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        self._tick_time(app)
        self._note_pattern(app, text or "")
        # лёгкий сдвиг настроения от тона
        low = (text or "").lower()
        if any(w in low for w in ("спасибо", "молодец", "любим", "рада", "класс")):
            self._set_mood(app, "happy", 0.75)
        elif any(w in low for w in ("дур", "туп", "бесит", "заткни", "достал")):
            self._set_mood(app, "annoyed", 0.7)
        elif any(w in low for w in ("скуч", "груст", "плохо", "устал")):
            self._set_mood(app, "sad", 0.55)
        elif any(w in low for w in ("секс", "голая", "18+", "пошл", "хочу тебя")):
            if app.state.get("character_nsfw"):
                self._set_mood(app, "flirty", 0.85)
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not messages:
            return messages
        self._tick_time(app)
        block = self._system_block(app)
        if messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + "\n\n" + block
        else:
            messages.insert(0, {"role": "system", "content": block})
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        # подтянуть mood из [ANIM:] если есть
        import re
        m = re.search(r"\[ANIM:([a-zA-Z0-9_]+)\]", reply or "")
        if m:
            anim = m.group(1).lower()
            map_anim = {
                "happy": "happy", "smile": "happy", "laugh": "happy",
                "sad": "sad", "cry": "sad",
                "angry": "annoyed", "annoyed": "annoyed",
                "flirty": "flirty", "love": "flirty", "lust": "flirty", "blush": "flirty",
                "thinking": "curious", "searching": "curious",
                "shy": "shy",
            }
            if anim in map_anim:
                self._set_mood(app, map_anim[anim], None)
        return reply

    # ---------- time / mood / profile block ----------
    def _tick_time(self, app: AppContext) -> None:
        now = datetime.now()
        app.state["local_time"] = now.strftime("%H:%M")
        app.state["local_date"] = now.strftime("%Y-%m-%d")
        app.state["local_weekday"] = _WEEKDAYS[now.weekday()]
        app.state["local_hour"] = now.hour
        if now.hour < 6:
            app.state["day_part"] = "ночь"
        elif now.hour < 12:
            app.state["day_part"] = "утро"
        elif now.hour < 18:
            app.state["day_part"] = "день"
        else:
            app.state["day_part"] = "вечер"

    def _ensure_mood(self, app: AppContext) -> None:
        if not app.state.get("companion_mood"):
            app.state["companion_mood"] = "calm"
            app.state["companion_mood_energy"] = 0.5

    def _set_mood(self, app: AppContext, mood: str, energy: Optional[float]) -> None:
        app.state["companion_mood"] = mood
        if energy is not None:
            app.state["companion_mood_energy"] = float(energy)
        app.state["companion_mood_at"] = time.time()
        # связать с emotion-плагином
        pl = app.plugins.get("emotion")
        if pl and hasattr(pl, "set_context"):
            try:
                anim = {
                    "happy": "happy", "sad": "sad", "annoyed": "angry",
                    "flirty": "flirty", "curious": "thinking", "calm": "idle",
                    "shy": "shy", "lust": "flirty",
                }.get(mood, "idle")
                pl.set_context(app, anim, "companion_mood")
            except Exception:
                pass

    def _profile_lines(self, app: AppContext) -> List[str]:
        lines: List[str] = []
        # из memory store — факты с меткой профиль / важно
        mem = app.plugins.get("memory")
        store = getattr(mem, "store", None) if mem else None
        if store is not None:
            try:
                items = []
                if hasattr(store, "list_recent"):
                    items = store.list_recent(30) or []
                elif hasattr(store, "all"):
                    items = store.all() or []
                elif hasattr(store, "list"):
                    items = store.list(limit=30) or []
                for it in items:
                    text = it if isinstance(it, str) else (it.get("text") or it.get("content") or str(it))
                    t = str(text).strip()
                    low = t.lower()
                    if any(k in low for k in ("профиль:", "важно:", "пользовател", "меня зовут", "я люблю", "я не люблю", "нельзя", "можно")):
                        lines.append(t[:160])
                    if len(lines) >= 8:
                        break
            except Exception as e:
                print(f"companion: profile memory: {e}", flush=True)
        # явный state
        extra = app.state.get("user_profile_lines")
        if isinstance(extra, list):
            for t in extra[:5]:
                if t and str(t) not in lines:
                    lines.append(str(t)[:160])
        return lines

    def _system_block(self, app: AppContext) -> str:
        self._ensure_mood(app)
        mood = app.state.get("companion_mood", "calm")
        energy = app.state.get("companion_mood_energy", 0.5)
        scene = app.state.get("screen_scene", "idle")
        title = app.state.get("screen_react_title") or app.state.get("fg_title") or ""
        parts = [
            "[COMPANION]",
            f"Сейчас: {app.state.get('local_date')} {app.state.get('local_time')} ({app.state.get('local_weekday')}), {app.state.get('day_part')}.",
            f"Настроение персонажа: {mood} (energy={float(energy):.2f}). Отвечай в этом тоне, без упоминания служебных меток.",
            f"Сцена на экране: {scene}" + (f" | окно: {title[:80]}" if title else "") + ".",
        ]
        # подсказка по сцене
        hints = {
            "coding": "Пользователь, похоже, пишет код. Можно коротко помочь или похвалить удачное — но не мешать каждым сообщением.",
            "writing": "Пользователь пишет текст. Уместны правки стиля/структуры, если просят или очень явно нужно.",
            "movie": "Похоже, смотрит видео/фильм. Не спойлерить. Можно спросить впечатления.",
            "nsfw": "На экране 18+. Реагируй СТРОГО по карточке персонажа и policy (флирт или отказ).",
            "browsing": "Браузер. Не открывай поиск повторно без запроса.",
            "chat": "Мессенджер. Будь краткой, если не зовут в диалог.",
            "idle": "Нейтральный рабочий стол.",
        }
        if scene in hints:
            parts.append(hints[scene])
        prof = self._profile_lines(app)
        if prof:
            parts.append("Профиль/важное о пользователе:")
            parts.extend(f"- {p}" for p in prof)
        pats = self._top_patterns(6)
        if pats:
            parts.append("Паттерны запросов (часто): " + ", ".join(pats))
        nsfw = app.state.get("character_nsfw")
        if nsfw is True:
            parts.append("Персонаж NSFW-допуск: да (взрослое по запросу).")
        elif nsfw is False:
            parts.append("Персонаж NSFW-допуск: нет (полный отказ от пошлости).")
        return "\n".join(parts)

    # ---------- screen scene ----------
    def _on_tick(self, app: AppContext) -> None:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return
        self._tick_time(app)
        if app.get_plugin_setting(self.id, "mood_drift", True):
            self._mood_drift(app)
        scene, title, conf = self._classify_scene(app)
        prev = app.state.get("screen_scene")
        app.state["screen_scene"] = scene
        app.state["screen_react_title"] = title
        app.state["fg_title"] = title
        if scene != prev:
            print(f"companion: scene {prev} → {scene} conf={conf:.2f} «{title[:60]}»", flush=True)
            self._react_scene_mood(app, scene)
            self._last_scene = scene
            self._last_scene_at = time.time()
        if app.get_plugin_setting(self.id, "proactive", True):
            self._maybe_suggest(app, scene, title, conf)

    def _classify_scene(self, app: AppContext) -> tuple:
        title = self._fg_title()
        low = title.lower()
        # nsfw path / filename in title
        for scene, keys in _SCENE_HINTS.items():
            if any(k in low for k in keys):
                conf = 0.82 if scene == "nsfw" else 0.7
                return scene, title, conf
        # fallback: screen_react emotion context
        ctx = str(app.state.get("screen_react_context") or "")
        if ctx:
            for scene, keys in _SCENE_HINTS.items():
                if any(k in ctx.lower() for k in keys):
                    return scene, title or ctx[:80], 0.6
        return "idle", title, 0.4

    def _react_scene_mood(self, app: AppContext, scene: str) -> None:
        nsfw_ok = bool(app.state.get("character_nsfw"))
        if scene == "nsfw":
            self._set_mood(app, "flirty" if nsfw_ok else "shy", 0.8 if nsfw_ok else 0.6)
        elif scene == "coding":
            self._set_mood(app, "curious", 0.65)
        elif scene == "movie":
            self._set_mood(app, "calm", 0.55)
        elif scene == "writing":
            self._set_mood(app, "curious", 0.6)

    def _maybe_suggest(self, app: AppContext, scene: str, title: str, conf: float) -> None:
        if conf < 0.65:
            return
        if scene in ("idle", "browsing", "chat"):
            return
        cd = int(app.get_plugin_setting(self.id, "suggest_cooldown_min", 12) or 12) * 60
        if time.time() - self._last_suggest_at < cd:
            return
        # не во время busy
        window = getattr(app, "window", None)
        if window is not None and getattr(window, "_busy", False):
            return
        chance = int(app.get_plugin_setting(self.id, "suggest_chance", 35) or 35)
        if random.randint(1, 100) > chance:
            return
        # не сразу при старте сцены — подождать 30с
        if time.time() - self._last_scene_at < 30:
            return
        text = self._suggest_text(app, scene, title)
        if not text:
            return
        self._last_suggest_at = time.time()
        self._publish(app, text)
        print(f"companion: suggest scene={scene} «{text[:60]}»", flush=True)

    def _suggest_text(self, app: AppContext, scene: str, title: str) -> str:
        nsfw_ok = bool(app.state.get("character_nsfw"))
        mood = app.state.get("companion_mood", "calm")
        # короткие живые фразы без «Как я могу помочь»
        if scene == "coding":
            opts = [
                "Вижу, ты в коде. Если застрянешь на ошибке — кинь строку, разберём.",
                "Режим IDE… Могу глянуть логику функции, если покажешь кусок.",
                "Пахнет отладкой. Нужен свежий взгляд — позови.",
            ]
        elif scene == "writing":
            opts = [
                "Пишешь текст? Могу подправить стиль или структуру — скажи.",
                "Если нужен абзац яснее или короче — покажи фрагмент.",
            ]
        elif scene == "movie":
            opts = [
                "Похоже, что-то смотришь. Как оно?",
                "Кино-режим. Я рядом, без спойлеров.",
            ]
        elif scene == "nsfw":
            if nsfw_ok:
                opts = [
                    "Ого… экран горячий. Нравится, что открыто?",
                    "18+ на мониторе. Я не стесняюсь — если хочешь, продолжим тему.",
                ]
            else:
                opts = [
                    "На экране что-то слишком откровенное. Давай лучше к делу.",
                ]
        else:
            return ""
        return random.choice(opts)

    def _publish(self, app: AppContext, text: str) -> None:
        window = getattr(app, "window", None)
        if window is None:
            return
        try:
            # типичный UI: append_assistant / add_message
            for name in ("append_assistant_message", "add_assistant_message", "show_assistant"):
                fn = getattr(window, name, None)
                if callable(fn):
                    fn(text)
                    return
            # chat widget
            chat = getattr(window, "chat", None) or getattr(window, "chat_view", None)
            if chat and hasattr(chat, "append"):
                chat.append(f"<b>Ассистент:</b> {text}")
                return
        except Exception as e:
            print(f"companion: publish {e}", flush=True)

    def _mood_drift(self, app: AppContext) -> None:
        last = float(app.state.get("companion_mood_at") or 0)
        if last and time.time() - last < 600:
            return
        # медленно к calm
        mood = app.state.get("companion_mood")
        if mood in ("annoyed", "sad", "flirty", "lust"):
            if random.random() < 0.3:
                self._set_mood(app, "calm", 0.5)

    @staticmethod
    def _fg_title() -> str:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return (buf.value or "").strip()
        except Exception:
            return ""

    # ---------- patterns ----------
    def _patterns_path(self, app: AppContext) -> Path:
        root = Path(getattr(app.config, "DATA_DIR", Path("data")))
        cid = getattr(app.config, "ACTIVE_CHARACTER", "default") or "default"
        d = root / "personas" / "characters" / str(cid)
        d.mkdir(parents=True, exist_ok=True)
        return d / "user_patterns.json"

    def _load_patterns(self, app: AppContext) -> None:
        p = self._patterns_path(app)
        try:
            if p.is_file():
                self._patterns = json.loads(p.read_text(encoding="utf-8"))
            else:
                self._patterns = {}
        except Exception:
            self._patterns = {}

    def _save_patterns(self, app: AppContext) -> None:
        try:
            p = self._patterns_path(app)
            p.write_text(json.dumps(self._patterns, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"companion: save patterns {e}", flush=True)

    def _note_pattern(self, app: AppContext, text: str) -> None:
        low = text.lower().strip()
        keys = []
        if any(w in low for w in ("найди", "погугли", "поиск")):
            keys.append("search")
        if any(w in low for w in ("картин", "фото", "image")):
            keys.append("images")
        if any(w in low for w in ("код", "функц", "баг", "error", "python", "asyncio")):
            keys.append("code_help")
        if any(w in low for w in ("запомни", "память")):
            keys.append("memory")
        if any(w in low for w in ("экран", "монитор", "что видишь")):
            keys.append("screen")
        if any(w in low for w in ("18+", "секс", "пошл", "nsfw")):
            keys.append("nsfw_talk")
        if any(w in low for w in ("открой", "закрой", "папк", "файл")):
            keys.append("pc")
        for k in keys:
            self._patterns[k] = int(self._patterns.get(k, 0)) + 1
        # иногда сохраняем
        if sum(self._patterns.values()) % 5 == 0:
            self._save_patterns(app)

    def _top_patterns(self, n: int = 5) -> List[str]:
        items = sorted(self._patterns.items(), key=lambda x: -x[1])
        labels = {
            "search": "поиск в сети",
            "images": "картинки",
            "code_help": "помощь по коду",
            "memory": "память",
            "screen": "экран",
            "nsfw_talk": "взрослые темы",
            "pc": "управление ПК",
        }
        return [f"{labels.get(k, k)}×{v}" for k, v in items[:n] if v > 0]


def register():
    return PluginImpl()
