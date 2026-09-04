# -*- coding: utf-8 -*-
"""Минимальный конфиг ядра. Плагины добавляют свои ключи через settings.json."""
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
BASE_DIR = DATA_DIR

API_URL = os.environ.get("LISICHKA_API_URL", "http://127.0.0.1:1234/v1")
API_KEY = os.environ.get("LISICHKA_API_KEY", "lm-studio")
MODEL_NAME = "local-model"
TEMPERATURE = 0.4
MAX_TOKENS = 1000
LLM_TIMEOUT = 300
LLM_CONNECT_TIMEOUT = 5

SYSTEM_PROMPT = (
    "Ты полезный ассистент. Отвечай кратко и по делу на языке пользователя."
)

# плагины
PLUGINS_ENABLED = True
PLUGINS = {}
PLUGIN_SETTINGS = {}

# UI
WINDOW_TITLE = "Лисичка"
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 640

SETTINGS_FILE = str(DATA_DIR / "settings.json")

# персонаж
ACTIVE_CHARACTER = "default"
ACTIVE_USER = "default"
