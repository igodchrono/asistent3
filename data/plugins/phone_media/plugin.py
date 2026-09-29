# -*- coding: utf-8 -*-
"""Генератор картинок: сцена → LLM-промпт → qwen/sdxl/z → ComfyUI.

Если пользователь только сказал «нарисуй / сгенерируй картинку» без описания —
сначала проверяем/поднимаем ComfyUI и ждём сцену. Референс: вложение 📎
или последнее изображение в чате (img2img, если в графе есть LoadImage).
"""
from __future__ import annotations

import copy
import json
import mimetypes
import os
import random
import re
import asyncio
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from core.plugin_api import AppContext, HookResult, Plugin, SettingField
