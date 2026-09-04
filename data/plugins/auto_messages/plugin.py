# -*- coding: utf-8 -*-
"""Периодические инициативные сообщения ассистента."""
from __future__ import annotations

import random
import asyncio
from datetime import datetime
from typing import Any, Optional

from core.plugin_api import AppContext, Plugin, SettingField


class PluginImpl(Plugin):
	id = "auto_messages"
	name = "Авто-сообщения"
	version = "1.0.0"
	description = "Периодически отправляет короткие контекстные сообщения с эмоциональной реакцией."
	settings_tab = "own"
	settings_tab_title = "Авто-сообщения"
	settings_schema = [
		SettingField("enabled", "Включить авто-сообщения", "bool", False),
		SettingField("interval_minutes", "Проверять каждые (минут)", "int", 15, min_value=1, max_value=1440),
		SettingField("chance_percent", "Вероятность сообщения (%)", "int", 35, min_value=0, max_value=100),
		SettingField("quiet_start", "Начало тихого времени", "int", 23, min_value=0, max_value=23),
		SettingField("quiet_end", "Конец тихого времени", "int", 8, min_value=0, max_value=23),
		SettingField("allow_flirty", "Разрешить лёгкий флирт", "bool", True),
	]

	_MESSAGES = {
		"morning": (
			("happy", "Доброе утро. Как настроение сегодня?"),
			("sleepy", "Доброе утро… Ты уже проснулся или мне ещё немного подождать?"),
		),
		"day": (
			("thinking", "Как проходит день? Не забывай сделать небольшой перерыв."),
			("tired", "Ты давно не отвлекался? Может, немного передохнёшь?"),
			("sad", "Я рядом. Если день тяжёлый, можешь рассказать, что случилось."),
		),
		"evening": (
			("happy", "Вечер уже наступил. Как прошёл твой день?"),
			("tired", "Похоже, день был долгим. Постарайся сегодня немного отдохнуть."),
			("flirty", "Вечер располагает к тёплой компании. Я могу немного побыть рядом."),
		),
		"night": (
			("sleepy", "Уже поздно. Может, пора отложить дела и немного поспать?"),
			("tired", "Ты ещё не спишь? Береги себя, завтра понадобится энергия."),
			("flirty", "Тихая ночь… Можно просто немного поговорить наедине."),
		),
	}

	def __init__(self) -> None:
		self.app: Optional[AppContext] = None
		self._timer = None
		self._last_message_at = 0.0
		self._last_text = ""
		self._task = None

	def on_load(self, app: AppContext) -> None:
		self.app = app
		app.state["auto_messages_plugin"] = self
		self._start_timer(app)

	def on_shutdown(self, app: AppContext) -> None:
		if self._timer is not None:
			self._timer.stop()
			self._timer.deleteLater()
			self._timer = None
		if self._task is not None and not self._task.done():
			self._task.cancel()

	def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
		self._restart_timer(app)

	def _start_timer(self, app: AppContext) -> None:
		try:
			from PyQt5 import QtCore
		except ImportError:
			return
		self._timer = QtCore.QTimer()
		self._timer.timeout.connect(lambda: self._tick(app))
		self._restart_timer(app)

	def _restart_timer(self, app: AppContext) -> None:
		if self._timer is None:
			return
		minutes = int(app.get_plugin_setting(self.id, "interval_minutes", 15) or 15)
		self._timer.start(max(1, minutes) * 60 * 1000)

	def _tick(self, app: AppContext) -> None:
		if not app.get_plugin_setting(self.id, "enabled", False):
			return
		window = getattr(app, "window", None)
		if window is None or getattr(window, "_busy", False) or not getattr(window, "isVisible", lambda: True)():
			return
		if self._quiet_time(app):
			return
		chance = int(app.get_plugin_setting(self.id, "chance_percent", 35) or 0)
		if random.randrange(100) >= max(0, min(100, chance)):
			return
		emotion, _ = self._choose_message(app)
		self._last_message_at = datetime.now().timestamp()
		self._apply_emotion(app, emotion)
		engine = getattr(window, "engine", None)
		if engine is None or not hasattr(engine, "generate_proactive"):
			return
		self._task = asyncio.ensure_future(self._generate(engine, window, app, emotion))

	async def _generate(self, engine: Any, window: Any, app: AppContext, emotion: str) -> None:
		period = self._period()
		user_mood = str(app.state.get("emotion", "neutral"))
		instruction = (
			"Напиши одно короткое инициативное сообщение пользователю от лица ассистента. "
			f"Сейчас {period}, текущая эмоция ассистента: {emotion}, настроение пользователя: {user_mood}. "
			"Сообщение должно быть естественным, тёплым и уместным, без упоминания правил, "
			"таймера или генерации. Не используй откровенный сексуальный текст; допустим лёгкий флирт."
		)
		try:
			text = await engine.generate_proactive(instruction)
			if text and text != self._last_text and not getattr(window, "_busy", False):
				self._last_text = text
				if hasattr(window, "publish_assistant_message"):
					window.publish_assistant_message(text)
		except Exception as exc:
			print(f"auto_messages: LLM generation failed: {exc}", flush=True)

	def _choose_message(self, app: AppContext) -> tuple[str, str]:
		period = self._period()
		period_key = {"утро": "morning", "день": "day", "вечер": "evening", "ночь": "night"}[period]
		options = list(self._MESSAGES[period_key])
		if not app.get_plugin_setting(self.id, "allow_flirty", True):
			options = [item for item in options if item[0] != "flirty"] or options
		current = str(app.state.get("emotion", "neutral"))
		matching = [item for item in options if item[0] == current]
		return random.choice(matching or options)

	@staticmethod
	def _period() -> str:
		hour = datetime.now().hour
		return "утро" if 5 <= hour < 11 else "день" if 11 <= hour < 18 else "вечер" if 18 <= hour < 23 else "ночь"

	@staticmethod
	def _apply_emotion(app: AppContext, emotion: str) -> None:
		plugin = app.plugins.get("emotion") or app.state.get("emotion_plugin")
		if plugin is not None and hasattr(plugin, "set_context"):
			plugin.set_context(app, emotion, "auto_message")

	@staticmethod
	def _quiet_time(app: AppContext) -> bool:
		hour = datetime.now().hour
		start = int(app.get_plugin_setting("auto_messages", "quiet_start", 23) or 0)
		end = int(app.get_plugin_setting("auto_messages", "quiet_end", 8) or 0)
		return hour >= start or hour < end if start > end else start <= hour < end
