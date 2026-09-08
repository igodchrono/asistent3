# -*- coding: utf-8 -*-
"""Tool: describe_screen — снимок + vision LLM / сохранение контекста."""
from __future__ import annotations

import base64
import io
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, HookResult, Plugin, SettingField


class PluginImpl(Plugin):
    id = "screen_vision"
    name = "Видение экрана"
    version = "2.0.0"
    description = "Исполнитель describe_screen (intent)."
    settings_tab = "own"
    settings_tab_title = "Видение экрана"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("max_side", "Макс. сторона снимка", "int", 1600, min_value=400, max_value=4000),
    ]

    def on_load(self, app: AppContext) -> None:
        app.state["screen_vision_plugin"] = self

    def on_user_message(self, text, app):
        # не перехватываем — describe через intent; pass-through для selftest OK
        return None

    def register_tools(self, app: AppContext) -> None:
        app.tools["describe_screen"] = self.tool_describe_screen

    def tool_describe_screen(self, app: AppContext, **kwargs) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return "Видение экрана выключено."
        path = self.capture(app)
        if not path:
            return "Не удалось сделать снимок (нужен Pillow / mss)."
        app.state["screen_vision_last_path"] = str(path)
        app.state["screen_vision_just_captured"] = True
        # если есть LLM — краткое описание синхронно через chat_once невозможно из sync tool
        # chat_engine after tool already returned; description comes if we inject for next turn
        # Попробуем быстрый OCR/заголовок окна через screen_react state
        title = str(app.state.get("screen_react_title") or "")
        blob = str(app.state.get("screen_react_context") or "")
        hint = (title + " " + blob).strip()
        if hint:
            keys = self._keywords(hint)
            app.state["screen_vision_last_desc"] = hint[:800]
            app.state["screen_vision_search_query"] = keys
            return f"Снимок экрана сохранён. На экране roughly: {hint[:300]}"
        app.state["screen_vision_last_desc"] = f"screenshot:{path.name}"
        return (
            "Снимок экрана сделан. Открой его в следующем сообщении через чат "
            "или спроси ещё раз — модель опишет картинку, если vision доступен."
        )

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        # если только что capture и идём в chat — прикрепить image
        if not app.state.pop("screen_vision_attach", None) and not app.state.get("screen_vision_just_captured"):
            return messages
        path = app.state.get("screen_vision_last_path")
        if not path:
            return messages
        try:
            raw = Path(path).read_bytes()
            encoded = base64.b64encode(raw).decode("ascii")
        except Exception:
            return messages
        target = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        if target is None:
            return messages
        prompt = target.get("content") if isinstance(target.get("content"), str) else "Что на экране?"
        target["content"] = [
            {"type": "text", "text": str(prompt) + "\nПроанализируй снимок экрана."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ]
        app.state["screen_vision_just_captured"] = False
        app.state["screen_vision_attach"] = False
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        text = (reply or "").strip()
        if not text:
            return reply
        if app.state.get("screen_vision_last_path") or "вижу" in text.lower() or "экран" in text.lower():
            app.state["screen_vision_last_desc"] = text[:1200]
            keys = self._keywords(text)
            if keys:
                app.state["screen_vision_search_query"] = keys
                print(f"screen_vision: search_query={keys!r}", flush=True)
            if any(p in text.lower() for p in ("похож", "similar", "найти картин")):
                app.state["screen_vision_pending_similar"] = True
        return reply

    def capture(self, app: AppContext) -> Optional[Path]:
        try:
            from PIL import Image, ImageGrab
        except ImportError:
            return None
        try:
            try:
                import mss
                with mss.mss() as sct:
                    mon = sct.monitors[0]
                    shot = sct.grab(mon)
                    from PIL import Image as PILImage
                    image = PILImage.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            except Exception:
                image = ImageGrab.grab(all_screens=True)
            max_side = int(app.get_plugin_setting(self.id, "max_side", 1600) or 1600)
            image.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=86)
            base = Path(getattr(app.config, "DATA_DIR", Path("data"))) / "cache"
            base.mkdir(parents=True, exist_ok=True)
            path = base / "screen_last.jpg"
            path.write_bytes(buf.getvalue())
            return path
        except Exception as e:
            print(f"screen_vision: {e}", flush=True)
            return None

    @staticmethod
    def _keywords(text: str) -> str:
        stop = {
            "на", "в", "и", "с", "что", "как", "это", "экран", "монитор", "вижу",
            "изображение", "картинка", "хозяин", "можно", "хочешь", "похожие",
        }
        words = []
        for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", text or ""):
            lw = w.lower()
            if lw in stop:
                continue
            if lw not in words:
                words.append(lw)
            if len(words) >= 8:
                break
        return " ".join(words)


def register():
    return PluginImpl()
