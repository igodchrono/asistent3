# -*- coding: utf-8 -*-
"""Открытие браузера и поиск информации в интернете."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, unquote

from core.plugin_api import AppContext, HookResult, Plugin, SettingField


class PluginImpl(Plugin):
	id = "browser_search"
	name = "Браузер и поиск"
	version = "1.0.0"
	description = "Открытие браузера, поиск информации, картинок и видео."
	settings_tab = "own"
	settings_tab_title = "Браузер и поиск"
	settings_schema = [
		SettingField("enabled", "Включить браузер и поиск", "bool", True),
		SettingField(
			"search_engine",
			"Поисковая система",
			"choice",
			"google",
			choices=["google", "yandex", "bing", "duckduckgo"],
		),
		SettingField(
			"browser_name",
			"Установленный браузер",
			"choice",
			"default",
			choices=["default", "chrome", "edge", "firefox", "yandex", "opera", "brave"],
		),
		SettingField("browser_path", "Путь к браузеру", "str", ""),
		SettingField("open_browser", "Открывать браузер при поиске", "bool", True),
		SettingField("open_best_result", "Открывать первый найденный результат", "bool", True),
	]

	def __init__(self):
		self.app: Optional[AppContext] = None

	def on_load(self, app: AppContext) -> None:
		self.app = app
		app.state["browser_search_plugin"] = self

	def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
		if not app.get_plugin_setting(self.id, "enabled", True):
			return None
		self.app = app
		command = self._parse(text)
		if command is None:
			return None
		action, query = command
		try:
			if action == "open_browser":
				comment = self._set_emotion_context(app, "searching", "", "browser_open")
				opened = self._open_url("about:blank", app)
				message = "Браузер открыт." if opened else "Не удалось открыть браузер."
				return HookResult(True, f"{comment} {message}" if comment else message)
			return HookResult(True, self._search(query, app))
		except Exception as exc:
			return HookResult(True, f"Ошибка браузера или поиска: {exc}")

	@staticmethod
	def _normalize(text: str) -> str:
		text = (text or "").lower().strip()
		spelling = {
			"интеренете": "интернете",
			"поискк": "поиск",
			"нади": "найди",
			"найти": "найди",
			"кортинки": "картинки",
			"картинкы": "картинки",
			"зхентай": "хентай",
			"хентайй": "хентай",
			"изображеня": "изображения",
		}
		for wrong, correct in spelling.items():
			text = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", correct, text)
		return re.sub(r"\s+", " ", text.strip(" .,!?:;"))

	def _parse(self, text: str) -> Optional[Tuple[str, str]]:
		value = self._normalize(text)
		if re.search(r"\b(?:на|с)\s+диск(?:е|а)?\s+[a-z]\b|\bдиск\s+[a-z]:?\b", value):
			return None
		if value in (
			"открой браузер", "открыть браузер", "запусти браузер", "запустить браузер",
			"открой интернет", "открыть интернет",
		):
			return "open_browser", ""

		prefixes = (
			"найди в интернете", "найди в интернете информацию о", "найди информацию о",
			"поищи в интернете", "поиск информации о", "поиск в интернете",
			"поищи", "найди", "поиск",
		)
		for prefix in prefixes:
			if value == prefix:
				return None
			if value.startswith(prefix + " "):
				query = value[len(prefix):].strip()
				return ("search", query) if query else None
		return None

	def _search(self, query: str, app: AppContext) -> str:
		intent = self._search_intent(query)
		fallback = "flirty" if any(word in query.lower() for word in ("хентай", "эрот", "18+")) else "searching"
		comment = self._set_emotion_context(app, fallback, query, f"search:{intent}")
		search_url = self._search_page_url(query, intent, app)
		opened: List[str] = []

		if app.get_plugin_setting(self.id, "open_browser", True):
			if self._open_url(search_url, app):
				opened.append("поиск")
			if (
				app.get_plugin_setting(self.id, "open_best_result", True)
				and intent == "web"
			):
				best = self._fetch_best_result(query)
				if best and self._open_url(best, app):
					opened.append("результат")
		else:
			prefix = f"{comment} " if comment else ""
			return f"{prefix}Поиск подготовлен, но открытие браузера отключено: {query}"

		if not opened:
			prefix = f"{comment} " if comment else ""
			return f"{prefix}Не удалось открыть браузер. Проверьте путь к браузеру в настройках."
		prefix = f"{comment} " if comment else ""
		if intent == "images":
			return f"{prefix}Открыт поиск картинок: {query}"
		if intent == "video":
			return f"{prefix}Открыт поиск видео: {query}"
		if "результат" in opened:
			return f"{prefix}Открыт поиск и наилучший найденный результат во второй вкладке: {query}"
		return f"{prefix}Открыт поиск: {query}"

	@staticmethod
	def _set_emotion_context(app: AppContext, emotion: str, text: str, source: str) -> str:
		plugin = app.plugins.get("emotion") or app.state.get("emotion_plugin")
		if plugin is not None and hasattr(plugin, "set_context"):
			if hasattr(plugin, "apply_operation"):
				return plugin.apply_operation(app, emotion, text, source)
			plugin.set_context(app, emotion, source)
		if emotion == "searching":
			return "Сейчас посмотрю, что найдётся в интернете."
		return "Секунду, выполняю запрос."

	@staticmethod
	def _search_intent(query: str) -> str:
		text = (query or "").lower()
		if any(word in text for word in ("картин", "фото", "изображен", "images", "pics")):
			return "images"
		if any(word in text for word in ("видео", "youtube", "ютуб", "ролик")):
			return "video"
		return "web"

	@staticmethod
	def _search_page_url(query: str, intent: str, app: AppContext) -> str:
		engine = str(app.get_plugin_setting("browser_search", "search_engine", "google") or "google").lower()
		encoded = quote_plus(query)
		if intent == "images":
			if engine == "yandex":
				return f"https://yandex.ru/images/search?text={encoded}"
			if engine == "bing":
				return f"https://www.bing.com/images/search?q={encoded}"
			return f"https://www.google.com/search?tbm=isch&q={encoded}"
		if intent == "video":
			return f"https://www.youtube.com/results?search_query={encoded}"
		if engine == "yandex":
			return f"https://yandex.ru/search/?text={encoded}"
		if engine == "bing":
			return f"https://www.bing.com/search?q={encoded}"
		if engine == "duckduckgo":
			return f"https://duckduckgo.com/?q={encoded}"
		return f"https://www.google.com/search?q={encoded}"

	@staticmethod
	def _fetch_best_result(query: str) -> Optional[str]:
		try:
			url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
			request = urllib.request.Request(
				url,
				headers={"User-Agent": "Mozilla/5.0 LisichkaSearch/1.0"},
			)
			with urllib.request.urlopen(request, timeout=4) as response:
				html = response.read().decode("utf-8", errors="ignore")
			links = re.findall(
				r'<a[^>]+class="result__a"[^>]+href="([^"<>]+)"[^>]*>(.*?)</a>',
				html,
				flags=re.I | re.S,
			)
			if not links:
				links = [(link, "") for link in re.findall(r'href="(https?://[^"<>]+)"', html, flags=re.I)]
			blocked = ("duckduckgo.com", "google.com/search", "yandex.", "bing.com/search", "javascript:")
			words = [word for word in re.findall(r"[\wа-яё]{4,}", query.lower())]
			candidates = []
			for link, title in links:
				link = unquote(link)
				title = html_module.unescape(re.sub(r"<[^>]+>", " ", title)).lower()
				if not link.startswith("http") or any(item in link.lower() for item in blocked):
					continue
				score = sum(1 for word in words if word in title or word in link.lower())
				candidates.append((score, link))
			if candidates:
				return max(candidates, key=lambda item: item[0])[1]
		except Exception:
			return None
		return None

	def _open_url(self, url: str, app: AppContext) -> bool:
		browser_path = str(app.get_plugin_setting("browser_search", "browser_path", "") or "").strip()
		browser_path = os.path.expandvars(browser_path)
		browser_name = str(app.get_plugin_setting("browser_search", "browser_name", "default") or "default").lower()
		if not browser_path or not os.path.isfile(browser_path):
			browser_path = self._find_browser(browser_name)
		if browser_path:
			subprocess.Popen(
				[browser_path, url],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			return True
		try:
			if webbrowser.open_new_tab(url):
				return True
		except Exception:
			pass
		if sys.platform == "win32":
			try:
				os.startfile(url)
				return True
			except Exception:
				pass
		return False

	@staticmethod
	def _find_browser(name: str) -> str:
		if name == "default":
			return ""
		local = os.environ.get("LOCALAPPDATA", "")
		program_files = os.environ.get("PROGRAMFILES", r"C:\\Program Files")
		program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")
		roots = [local, program_files, program_files_x86]
		candidates = {
			"chrome": [r"Google\Chrome\Application\chrome.exe"],
			"edge": [r"Microsoft\Edge\Application\msedge.exe"],
			"firefox": [r"Mozilla Firefox\firefox.exe"],
			"yandex": [r"Yandex\YandexBrowser\Application\browser.exe"],
			"opera": [r"Programs\Opera\launcher.exe", r"Opera\launcher.exe"],
			"brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
		}.get(name, [])
		for root in roots:
			for relative in candidates:
				path = os.path.join(root, relative)
				if os.path.isfile(path):
					return path
		return ""
