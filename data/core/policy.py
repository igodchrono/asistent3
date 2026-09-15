# -*- coding: utf-8 -*-
"""Совместимость. Цензура контента — у модели. Здесь только флаги карточки."""
from core._guard import (  # noqa: F401
    build_policy_prompt,
    character_is_nsfw,
    character_policy,
    parse_character_policy,
    sanitize_card,
    scrub_for_llm,
)
