# -*- coding: utf-8 -*-
"""Захват экрана и передача изображения мультимодальной модели."""
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
	version = "1.0.0"
	description = "Делает снимок выбранного монитора и передаёт его vision-модели."
	settings_tab = "own"
	settings_tab_title = "Видение экрана"
	settings_schema = [
		SettingField("enabled", "Включить видение экрана", "bool", True),
		SettingField("max_side", "Максимальная сторона снимка", "int", 1600, min_value=640, max_value=4096),
		SettingField("monitor", "Монитор по умолчанию", "choice", "all", choices=["all", "primary", "1", "2", "3"]),
		SettingField("save_screenshot", "Сохранять последний снимок", "bool", True),
	]

	_COMMAND_RE = re.compile(
		r"(?:посмотри|посмотреть|что|покажи|сделай|сфотографируй|прочитай).{0,30}"
		r"(?:экран|монитор|скрин|изображен|дисплей)", re.IGNORECASE,
	)

	def __init__(self) -> None:
		self.app: Optional[AppContext] = None
		self._last_capture = 0.0

	def on_load(self, app: AppContext) -> None:
		self.app = app
		app.state["screen_vision_plugin"] = self

	def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
		if not self._enabled(app) or not self._is_screen_request(text):
			return None
		app.state["screen_vision_request"] = (text or "Что на экране?").strip()
		return None

	def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
		if not self._enabled(app) or not messages:
			return messages
		text = self._last_user_text(messages)
		if not self._is_screen_request(text) and not app.state.pop("screen_vision_request", None):
			return messages
		path = self.capture(text, app)
		if not path:
			app.state["screen_vision_error"] = "Не удалось сделать снимок экрана. Установите Pillow."
			return messages
		encoded = self._base64(path)
		if not encoded:
			return messages
		target = next((item for item in reversed(messages) if item.get("role") == "user"), None)
		if target is None:
			return messages
		prompt = text or "Что находится на моём экране?"
		target["content"] = [
			{"type": "text", "text": prompt + "\nПроанализируй приложенный снимок экрана."},
			{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
		]
		app.state["screen_vision_last_path"] = str(path)
		return messages

	def capture(self, text: str, app: AppContext) -> Optional[Path]:
		try:
			from PIL import Image, ImageGrab
		except ImportError:
			return None
		try:
			monitor = self._monitor(text, app)
			image = self._grab_monitor(Image, ImageGrab, monitor)
			max_side = int(app.get_plugin_setting(self.id, "max_side", 1600) or 1600)
			image.thumbnail((max_side, max_side))
			data = io.BytesIO()
			image.convert("RGB").save(data, format="JPEG", quality=86, optimize=True)
			base = Path(getattr(app.config, "DATA_DIR", Path("data"))) / "cache"
			base.mkdir(parents=True, exist_ok=True)
			path = base / "screen_last.jpg"
			path.write_bytes(data.getvalue())
			(base / "screen_last.txt").write_text(self._monitor_label(monitor), encoding="utf-8")
			self._last_capture = time.time()
			return path
		except Exception as exc:
			print(f"screen_vision: capture failed: {exc}", flush=True)
			return None

	@staticmethod
	def _grab_monitor(image_module: Any, image_grab: Any, monitor: str) -> Any:
		"""Захватить весь рабочий стол или конкретный монитор без обязательного mss."""
		try:
			import mss
			from PIL import Image

			with mss.mss() as screens:
				monitors = screens.monitors[1:]
				if not monitors:
					raise RuntimeError("мониторы не найдены")
				if monitor == "all":
					box = screens.monitors[0]
				elif monitor == "primary":
					box = monitors[0]
				else:
					index = max(1, min(int(monitor), len(monitors))) - 1
					box = monitors[index]
				shot = screens.grab(box)
				return Image.frombytes("RGB", shot.size, shot.rgb)
		except (ImportError, ValueError, RuntimeError):
			if monitor == "all":
				try:
					return image_grab.grab(all_screens=True)
				except TypeError:
					return image_grab.grab()
			return image_grab.grab()

	@staticmethod
	def _enabled(app: AppContext) -> bool:
		return bool(app.get_plugin_setting("screen_vision", "enabled", True))

	@classmethod
	def _is_screen_request(cls, text: str) -> bool:
		value = (text or "").lower()
		return bool(cls._COMMAND_RE.search(value) or any(
			phrase in value for phrase in ("скриншот экрана", "снимок экрана", "на моём экране", "на моем экране")
		))

	@staticmethod
	def _last_user_text(messages: List[Dict[str, Any]]) -> str:
		for message in reversed(messages):
			if message.get("role") == "user":
				content = message.get("content", "")
				return content if isinstance(content, str) else ""
		return ""

	@staticmethod
	def _monitor(text: str, app: AppContext) -> str:
		value = (text or "").lower()
		for number in ("1", "2", "3"):
			if f"монитор {number}" in value or f"экране {number}" in value:
				return number
		return str(app.get_plugin_setting("screen_vision", "monitor", "all") or "all")

	@staticmethod
	def _monitor_label(monitor: str) -> str:
		return "все мониторы" if monitor == "all" else f"монитор {monitor}"

	@staticmethod
	def _base64(path: Path) -> Optional[str]:
		try:
			return base64.b64encode(path.read_bytes()).decode("ascii")
		except OSError:
			return None
