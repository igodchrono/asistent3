# -*- coding: utf-8 -*-
"""Безопасное управление Windows через команды чата."""
from __future__ import annotations

import ctypes
import fnmatch
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.plugin_api import AppContext, HookResult, Plugin, SettingField


_CONFIRM_YES = ("да", "подтверждаю", "подтвердить", "выполняй", "закрывай", "ок", "окей")
_CONFIRM_NO = ("нет", "отмена", "отменить", "не надо", "не выполняй")
_APP_ALIASES = {
	"блокнот": "notepad.exe",
	"notepad": "notepad.exe",
	"калькулятор": "calc.exe",
	"calculator": "calc.exe",
	"проводник": "explorer.exe",
	"explorer": "explorer.exe",
	"диспетчер задач": "taskmgr.exe",
	"диспетчер задачь": "taskmgr.exe",
	"task manager": "taskmgr.exe",
}

_SPELLING_FIXES = {
	"задачь": "задач",
	"деспетчер": "диспетчер",
	"диспечер": "диспетчер",
	"диспетчер задачь": "диспетчер задач",
	"дис": "диск",
	"калькуляторр": "калькулятор",
	"проводникк": "проводник",
	"громчее": "громче",
	"тишее": "тише",
	"следущий": "следующий",
	"предидущий": "предыдущий",
	"предыдущи": "предыдущий",
	"сверниь": "сверни",
	"разверниь": "разверни",
	"откройй": "открой",
	"открит": "открой",
	"запустиь": "запусти",
	"програму": "программу",
	"зхентай": "хентай",
	"хентайй": "хентай",
}


class PluginImpl(Plugin):
	id = "pc_control"
	name = "Управление ПК"
	version = "1.0.0"
	description = "Управление приложениями, мультимедиа, окнами и получение информации о Windows."
	settings_tab = "own"
	settings_tab_title = "Управление ПК"
	settings_schema = [
		SettingField("enabled", "Включить управление ПК", "bool", True),
		SettingField("confirmation_timeout", "Таймаут подтверждения (сек.)", "int", 20, min_value=5, max_value=120),
		SettingField("allow_process_close", "Разрешить закрытие программ", "bool", True),
		SettingField("allow_window_control", "Разрешить управление окнами", "bool", True),
	]

	def __init__(self):
		self.app: Optional[AppContext] = None
		self._pending: Optional[Dict[str, Any]] = None

	def on_load(self, app: AppContext) -> None:
		self.app = app
		app.state["pc_control_plugin"] = self

	def on_shutdown(self, app: AppContext) -> None:
		self._pending = None

	def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
		if not app.get_plugin_setting(self.id, "enabled", True) or sys.platform != "win32":
			return None
		self.app = app
		text = (text or "").strip()
		if not text:
			return None

		confirmation = self._handle_confirmation(text, app)
		if confirmation is not None:
			return confirmation

		command = self._parse(text)
		if command is None:
			return None
		action, argument = command

		if action in {"close_process", "close_window"}:
			comment = self._set_emotion_context(app, self._emotion_for_action(action), f"confirm:{action}", f"{action} {argument}")
			if action == "close_process" and not app.get_plugin_setting(self.id, "allow_process_close", True):
				return HookResult(True, "Закрытие программ отключено в настройках.")
			if action == "close_window" and not app.get_plugin_setting(self.id, "allow_window_control", True):
				return HookResult(True, "Управление окнами отключено в настройках.")
			self._pending = {"action": action, "argument": argument, "created": time.time()}
			target = argument or "активное окно"
			prefix = f"{comment} " if comment else ""
			return HookResult(True, f"{prefix}Подтвердите действие: закрыть {target}? Ответьте «да» или «нет».")

		try:
			reply = self._execute(action, argument)
			emotion_for = "local_search" if action == "search_files" else self._emotion_for_action(action)
			comment = self._set_emotion_context(app, emotion_for, f"pc:{action}", f"{action} {argument}")
			if comment:
				reply = f"{comment} {reply}"
		except Exception as exc:
			comment = self._set_emotion_context(app, "sad", f"pc:error:{action}", f"ошибка {action}")
			reply = f"{comment} Не удалось выполнить команду: {exc}" if comment else f"Не удалось выполнить команду: {exc}"
		return HookResult(True, reply)

	@staticmethod
	def _emotion_for_action(action: str) -> str:
		# Разделение локального поиска и общего "searching".
		if action == "search_files":
			return "local_search"
		# По умолчанию используем общее состояние поиска/мыслей.
		return "searching"

	def _set_emotion_context(app: AppContext, emotion: str, source: str, text: str = "") -> str:
		plugin = app.plugins.get("emotion") or app.state.get("emotion_plugin")
		if plugin is not None and hasattr(plugin, "set_context"):
			if hasattr(plugin, "apply_operation"):
				return plugin.apply_operation(app, emotion, text, source)
			plugin.set_context(app, emotion, source)
			if hasattr(plugin, "operation_comment"):
				return plugin.operation_comment(emotion)
		return ""

	def _handle_confirmation(self, text: str, app: AppContext) -> Optional[HookResult]:
		if self._pending is None:
			return None
		timeout = int(app.get_plugin_setting(self.id, "confirmation_timeout", 20) or 20)
		if time.time() - self._pending["created"] > timeout:
			self._pending = None
			return HookResult(True, "Подтверждение истекло. Повторите команду.")
		normalized = self._normalize(text)
		if normalized in _CONFIRM_NO or any(normalized == phrase for phrase in _CONFIRM_NO):
			self._pending = None
			return HookResult(True, "Действие отменено.")
		if normalized in _CONFIRM_YES or any(normalized == phrase for phrase in _CONFIRM_YES):
			pending = self._pending
			self._pending = None
			try:
				reply = self._execute(pending["action"], pending["argument"])
				emotion_for = "local_search" if pending["action"] == "search_files" else self._emotion_for_action(pending["action"])
				comment = self._set_emotion_context(app, emotion_for, f"pc:{pending['action']}", f"{pending['action']} {pending['argument']}")
				if comment:
					reply = f"{comment} {reply}"
				return HookResult(True, reply)
			except Exception as exc:
				comment = self._set_emotion_context(app, "sad", f"pc:error:{pending['action']}", f"ошибка {pending['action']}")
				message = f"Не удалось выполнить подтверждённое действие: {exc}"
				return HookResult(True, f"{comment} {message}" if comment else message)
		return None

	@staticmethod
	def _normalize(text: str) -> str:
		text = text.lower().strip(" .,!?:;")
		text = re.sub(r"\s+", " ", text)
		for wrong, correct in _SPELLING_FIXES.items():
			text = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", correct, text)
		return text

	def _parse(self, text: str) -> Optional[Tuple[str, str]]:
		value = self._normalize(text)
		if value in ("громче", "увеличь громкость", "сделай громче"):
			return "volume_up", ""
		if value in ("тише", "уменьши громкость", "сделай тише"):
			return "volume_down", ""
		if value in ("выключи звук", "выключить звук", "без звука", "mute"):
			return "mute", ""
		if value in ("включи звук", "включить звук"):
			return "mute", ""
		if value in ("пауза", "поставь на паузу", "продолжи воспроизведение", "воспроизведение"):
			return "media_play", ""
		if value in ("следующий трек", "следующая песня", "следующий"):
			return "media_next", ""
		if value in ("предыдущий трек", "предыдущая песня", "предыдущий"):
			return "media_prev", ""
		if value in ("сверни окно", "свернуть окно", "сверни активное окно"):
			return "minimize_window", ""
		if value in ("разверни окно", "развернуть окно", "восстанови окно"):
			return "restore_window", ""
		if value in ("переключи окно", "переключиться между окнами", "следующее окно"):
			return "switch_window", ""
		if value in ("закрой активное окно", "закрыть активное окно"):
			return "close_window", ""
		if value in ("информация о системе", "сведения о системе", "характеристики компьютера", "статус системы"):
			return "system_info", ""
		if value in ("загрузка процессора", "загрузка cpu", "загрузка памяти", "оперативная память"):
			return "system_info", ""
		if value in ("батарея", "заряд батареи", "состояние батареи"):
			return "battery_info", ""
		if value in ("свободное место", "место на диске", "диски"):
			return "disk_info", ""
		if value in ("сеть", "сетевой статус", "мой ip", "ip адрес", "айпи"):
			return "network_info", ""
		match = re.match(
			r"^(?:найди|найти|поищи)\s+(?:файл(?:ы)?|папк(?:у|и)|изображени(?:е|я)|картин(?:ку|ки))?\s*(.*?)\s+(?:на|в)\s+(?:диск|диске|диска)\s+([a-z])\s*:?[\\/]?$",
			value,
		)
		if match:
			query = match.group(1).strip() or "*"
			return "search_files", f"{match.group(2).upper()}:|{query}"
		match = re.match(r"^(?:найди|найти|поищи)\s+(.+?)\s+на\s+диске\s+([a-z])\s*:?[\\/]?$", value)
		if match:
			return "search_files", f"{match.group(2).upper()}:|{match.group(1).strip()}"

		match = re.match(r"^(?:открой|открыть|запусти|запустить)\s+(.+)$", value)
		if match:
			return "open", match.group(1).strip(' "\'')
		match = re.match(r"^(?:закрой|закрыть)\s+(?:диск|дис)\s+([a-z])$", value, re.IGNORECASE)
		if match:
			return "close_window", f"диск {match.group(1).upper()}:"
		match = re.match(r"^(?:закрой|закрыть)\s+(?:программу\s+)?(.+)$", value)
		if match:
			return "close_process", match.group(1).strip(' "\'')
		return None

	def _execute(self, action: str, argument: str) -> str:
		if action == "open":
			return self._open_target(argument)
		if action == "search_files":
			return self._search_files(argument)
		if action == "close_process":
			return self._close_process(argument)
		if action == "close_window":
			is_disk = bool(re.match(r"^диск\s+[a-z]:$", argument or "", re.IGNORECASE))
			hwnd = self._window_for_target(argument) if is_disk else self._last_external_window()
			if not hwnd:
				raise RuntimeError("не найдено внешнее активное окно (окно ассистента исключено)")
			self._win32().PostMessageW(hwnd, 0x0010, 0, 0)
			return "Команда закрытия активного окна отправлена."
		if action == "volume_up":
			self._media_key(0xAF)
			return "Громкость увеличена."
		if action == "volume_down":
			self._media_key(0xAE)
			return "Громкость уменьшена."
		if action == "mute":
			self._media_key(0xAD)
			return "Состояние звука переключено."
		if action == "media_play":
			self._media_key(0xB3)
			return "Воспроизведение переключено."
		if action == "media_next":
			self._media_key(0xB0)
			return "Включён следующий трек."
		if action == "media_prev":
			self._media_key(0xB1)
			return "Включён предыдущий трек."
		if action == "minimize_window":
			self._win32().ShowWindow(self._win32().GetForegroundWindow(), 6)
			return "Активное окно свёрнуто."
		if action == "restore_window":
			self._win32().ShowWindow(self._win32().GetForegroundWindow(), 9)
			return "Активное окно восстановлено."
		if action == "switch_window":
			self._media_key(0x09, alt=True)
			return "Переключение окна выполнено."
		if action == "system_info":
			return self._system_info()
		if action == "battery_info":
			return self._battery_info()
		if action == "disk_info":
			return self._disk_info()
		if action == "network_info":
			return self._network_info()
		return "Команда не поддерживается."

	@staticmethod
	def _search_files(argument: str) -> str:
		root_text, query = (argument.split("|", 1) + ["*"])[:2]
		root = Path(root_text.strip())
		if not root.exists() or not root.is_dir():
			raise FileNotFoundError(f"диск или папка не найдены: {root}")
		query = query.strip().lower() or "*"
		if query in {"картинки", "изображения", "изображение", "фото", "фотографии"}:
			patterns = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.bmp", "*.webp")
		elif query in {"документы", "документ", "текст"}:
			patterns = ("*.doc", "*.docx", "*.pdf", "*.txt", "*.rtf", "*.xls", "*.xlsx")
		else:
			patterns = (query if any(char in query for char in "*?") else f"*{query}*",)
		results = []
		started = time.monotonic()
		for current, directories, files in os.walk(root, topdown=True):
			directories[:] = [item for item in directories if item not in {"$Recycle.Bin", "System Volume Information"}]
			for name in files:
				if any(fnmatch.fnmatch(name.lower(), pattern) for pattern in patterns):
					results.append(str(Path(current) / name))
					if len(results) >= 30:
						break
			if len(results) >= 30 or time.monotonic() - started > 12:
				break
		if not results:
			return f"По запросу «{query}» на диске {root.drive or root} ничего не найдено."
		lines = "\n".join(f"{index}. {path}" for index, path in enumerate(results, 1))
		suffix = "\nПоказаны первые 30 результатов." if len(results) == 30 else ""
		return f"Найдено файлов: {len(results)}\n{lines}{suffix}"

	@staticmethod
	def _open_target(target: str) -> str:
		target = target.strip()
		drive = re.fullmatch(r"диск\s+([a-z])[:\\]?", target, re.IGNORECASE)
		if drive:
			target = f"{drive.group(1).upper()}:\\"
		alias = _APP_ALIASES.get(target.lower(), target)
		path = Path(os.path.expandvars(os.path.expanduser(alias)))
		if path.exists():
			os.startfile(str(path))
			return f"Открыто: {path}"
		executable = shutil.which(alias) or shutil.which(alias + ".exe")
		if executable:
			subprocess.Popen([executable], close_fds=True)
			return f"Запущено: {target}"
		raise FileNotFoundError(f"приложение или путь не найден: {target}")

	@staticmethod
	def _close_process(name: str) -> str:
		image = name.strip().strip('"\'')
		if not re.fullmatch(r"[\w .-]+(?:\.exe)?", image, re.IGNORECASE):
			raise ValueError("недопустимое имя процесса")
		if not image.lower().endswith(".exe"):
			image += ".exe"
		result = subprocess.run(["taskkill", "/IM", image, "/T"], capture_output=True, text=True, encoding="cp866", errors="replace")
		output = (result.stdout or result.stderr or "").strip()
		if result.returncode != 0:
			return f"Процесс {image} не найден или не закрыт."
		return f"Процесс {image} закрыт."

	@staticmethod
	def _win32():
		return ctypes.windll.user32

	@staticmethod
	def _last_external_window() -> int:
		"""Найти верхнее видимое окно не принадлежащее процессу ассистента."""
		user32 = ctypes.windll.user32
		current_pid = os.getpid()
		windows = []

		@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
		def callback(hwnd, _lparam):
			if not user32.IsWindowVisible(hwnd) or not user32.IsWindowEnabled(hwnd):
				return True
			pid = ctypes.c_ulong()
			user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
			if pid.value == current_pid:
				return True
			length = user32.GetWindowTextLengthW(hwnd)
			if length <= 0:
				return True
			buffer = ctypes.create_unicode_buffer(length + 1)
			user32.GetWindowTextW(hwnd, buffer, length + 1)
			if buffer.value.strip():
				windows.append(int(hwnd))
			return True

		user32.EnumWindows(callback, 0)
		return windows[0] if windows else 0

	@staticmethod
	def _window_for_target(target: str) -> int:
		match = re.search(r"диск\s+([a-z])", target or "", re.IGNORECASE)
		if not match:
			return 0
		needle = f"{match.group(1).upper()}:"
		user32 = ctypes.windll.user32
		current_pid = os.getpid()
		found = []

		@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
		def callback(hwnd, _lparam):
			if not user32.IsWindowVisible(hwnd):
				return True
			pid = ctypes.c_ulong()
			user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
			if pid.value == current_pid:
				return True
			length = user32.GetWindowTextLengthW(hwnd)
			buffer = ctypes.create_unicode_buffer(length + 1)
			user32.GetWindowTextW(hwnd, buffer, length + 1)
			if needle in buffer.value.upper():
				found.append(int(hwnd))
			return True

		user32.EnumWindows(callback, 0)
		return found[0] if found else 0

	@staticmethod
	def _media_key(key: int, alt: bool = False) -> None:
		user32 = ctypes.windll.user32
		if alt:
			user32.keybd_event(0x12, 0, 0, 0)
		user32.keybd_event(key, 0, 0, 0)
		user32.keybd_event(key, 0, 2, 0)
		if alt:
			user32.keybd_event(0x12, 0, 2, 0)

	@staticmethod
	def _system_info() -> str:
		memory = ctypes.c_ulonglong(0)
		class Memory(ctypes.Structure):
			_fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
						("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
						("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
						("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
						("extended", ctypes.c_ulonglong)]
		status = Memory()
		status.length = ctypes.sizeof(status)
		ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
		cpu = f"{PluginImpl._cpu_percent():.0f}%"
		return f"CPU: {cpu}; память: {status.memory_load}% (свободно {status.available // 1024**2} МБ)"

	@staticmethod
	def _cpu_percent() -> float:
		class FileTime(ctypes.Structure):
			_fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

		idle_1, kernel_1, user_1 = FileTime(), FileTime(), FileTime()
		idle_2, kernel_2, user_2 = FileTime(), FileTime(), FileTime()
		kernel32 = ctypes.windll.kernel32
		if not kernel32.GetSystemTimes(ctypes.byref(idle_1), ctypes.byref(kernel_1), ctypes.byref(user_1)):
			return 0.0
		time.sleep(0.1)
		if not kernel32.GetSystemTimes(ctypes.byref(idle_2), ctypes.byref(kernel_2), ctypes.byref(user_2)):
			return 0.0

		def value(item: FileTime) -> int:
			return (int(item.high) << 32) | int(item.low)

		idle = value(idle_2) - value(idle_1)
		total = (value(kernel_2) - value(kernel_1)) + (value(user_2) - value(user_1))
		return max(0.0, min(100.0, (1.0 - idle / total) * 100.0)) if total else 0.0

	@staticmethod
	def _battery_info() -> str:
		class Battery(ctypes.Structure):
			_fields_ = [("ac", ctypes.c_ubyte), ("status", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
						("reserved", ctypes.c_ubyte), ("time", ctypes.c_ulong), ("full", ctypes.c_ulong)]
		battery = Battery()
		if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(battery)):
			return "Не удалось получить состояние батареи."
		if battery.percent == 255:
			return "Информация о батарее недоступна."
		source = "от сети" if battery.ac else "от батареи"
		return f"Заряд батареи: {battery.percent}%, {source}."

	@staticmethod
	def _disk_info() -> str:
		values = []
		for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
			root = f"{letter}:\\"
			if os.path.exists(root):
				usage = shutil.disk_usage(root)
				values.append(f"{letter}: свободно {usage.free // 1024**3} ГБ из {usage.total // 1024**3} ГБ")
		return "Диски: " + ("; ".join(values) if values else "не найдены")

	@staticmethod
	def _network_info() -> str:
		hostname = socket.gethostname()
		try:
			ip = socket.gethostbyname(hostname)
		except Exception:
			ip = "н/д"
		return f"Имя компьютера: {hostname}; локальный IP: {ip}"
