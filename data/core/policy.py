# -*- coding: utf-8 -*-
"""Заглушка у пользователя.

Этот файл можно править — чат его НЕ вызывает.
Правила: только filter.json
Движок: core/_guard.py
"""
from core._guard import (  # noqa: F401
    build_policy_prompt,
    character_is_nsfw,
    character_policy,
    check_assistant_text,
    check_user_text,
    filter_path,
    load_policy,
    parse_character_policy,
    policy_path,
    sanitize_card,
    scrub_for_llm,
)
