# plugin_loader.py — загрузка паков из data/plugins/<имя>/
"""
Как personas: папка = плагин. Ядро не знает про эмоции / rag-расширения / etc.

Структура:
  data/plugins/<id>/plugin.json
  data/plugins/<id>/plugin.py     # обязателен: register() или class Plugin

plugin.py:
  PLUGIN_ID = "emotion"
  PLUGIN_ENABLED = True          # можно перебить settings.json PLUGINS_DISABLED

  def setup(assistant): ...
  def before_llm(assistant, user_text, state): ...
      state — dict с ключами anim, mood_addon (можно дополнять)

Автоподхват:
  1) import plugin_loader  (из main.py или конца assistant_core)
  2) plugin_loader.attach(assistant) после создания LMAssistant
  3) либо plugin_loader.install() — патчит LMAssistant.__init__
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_attached = False
_loaded: List[Any] = []


def plugins_root() -> Path:
    try:
        import config
        raw = getattr(config, "PLUGINS_DIR", None)
        if raw:
            p = Path(raw)
            if not p.is_absolute():
                base = Path(getattr(config, "DATA_DIR", None) or Path.cwd())
                p = base / p
            return p
        base = Path(getattr(config, "DATA_DIR", None) or Path.cwd())
        return base / "plugins"
    except Exception:
        return Path.cwd() / "plugins"


def _disabled_ids() -> set:
    try:
        import config
        raw = getattr(config, "PLUGINS_DISABLED", None) or []
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.split(",") if x.strip()]
        return {str(x).lower() for x in raw}
    except Exception:
        return set()


def _enabled_only() -> Optional[set]:
    try:
        import config
        raw = getattr(config, "PLUGINS_ENABLED", None)
        if raw is None:
            return None
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.split(",") if x.strip()]
        return {str(x).lower() for x in raw}
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_module(plugin_dir: Path):
    py = plugin_dir / "plugin.py"
    if not py.is_file():
        return None
    name = f"lisichka_plugin_{plugin_dir.name}"
    spec = importlib.util.spec_from_file_location(name, py)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def discover() -> List[Dict[str, Any]]:
    root = plugins_root()
    root.mkdir(parents=True, exist_ok=True)
    found = []
    disabled = _disabled_ids()
    only = _enabled_only()
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        pid = child.name.lower()
        meta = _load_json(child / "plugin.json")
        pid = str(meta.get("id") or pid).lower()
        enabled = meta.get("enabled", True)
        if pid in disabled:
            continue
        if only is not None and pid not in only:
            continue
        if enabled is False:
            continue
        found.append({"id": pid, "dir": child, "meta": meta})
    return found


def load_all() -> List[Any]:
    global _loaded
    if _loaded:
        return _loaded
    packs = []
    for item in discover():
        try:
            mod = _load_module(item["dir"])
            if mod is None:
                continue
            if hasattr(mod, "PLUGIN_ENABLED") and not bool(mod.PLUGIN_ENABLED):
                continue
            plugin = None
            if hasattr(mod, "register") and callable(mod.register):
                plugin = mod.register()
            elif hasattr(mod, "Plugin"):
                plugin = mod.Plugin()
            else:
                plugin = mod
            if plugin is None:
                continue
            setattr(plugin, "plugin_id", item["id"])
            setattr(plugin, "plugin_dir", item["dir"])
            setattr(plugin, "plugin_meta", item["meta"])
            packs.append(plugin)
            logger.info("plugin loaded: %s", item["id"])
        except Exception as e:
            logger.warning("plugin %s failed: %s", item["id"], e)
    _loaded = packs
    return packs


def _run_hook(plugin: Any, name: str, *args, **kwargs):
    fn = getattr(plugin, name, None)
    if callable(fn):
        return fn(*args, **kwargs)
    return None


def attach(assistant) -> List[Any]:
    """Повесить все плагины на живой LMAssistant. Идемпотентно."""
    packs = load_all()
    for p in packs:
        try:
            _run_hook(p, "setup", assistant)
        except Exception as e:
            logger.warning("plugin setup %s: %s", getattr(p, "plugin_id", p), e)

    _wrap_anim(assistant, packs)
    _wrap_mood(assistant, packs)
    try:
        assistant.plugins = {getattr(p, "plugin_id", id(p)): p for p in packs}
    except Exception:
        pass
    logger.info("plugins attached: %s", [getattr(p, "plugin_id", "?") for p in packs])
    return packs


def _wrap_anim(assistant, packs):
    sel = getattr(assistant, "anim_selector", None)
    if sel is None or not hasattr(sel, "select"):
        return
    if getattr(sel, "_plugin_wrapped", False):
        return
    orig = sel.select

    def select(user_text=None, **kwargs):
        text = user_text or kwargs.get("user_text") or ""
        state = {"anim": None, "mood_addon": "", "user_text": text}
        for p in packs:
            try:
                _run_hook(p, "before_llm", assistant, text, state)
            except Exception as e:
                logger.debug("before_llm %s: %s", getattr(p, "plugin_id", p), e)
        try:
            anim = orig(user_text=text, **{k: v for k, v in kwargs.items() if k != "user_text"})
        except TypeError:
            anim = orig(text)
        if not anim or str(anim).lower() in ("neutral", "none"):
            if state.get("anim"):
                anim = state["anim"]
        state["anim"] = anim
        for p in packs:
            try:
                _run_hook(p, "after_anim", assistant, text, state)
            except Exception:
                pass
        return anim

    sel.select = select
    sel._plugin_wrapped = True


def _wrap_mood(assistant, packs):
    ctx = getattr(assistant, "context", None)
    if ctx is None or not hasattr(ctx, "get_mood_prompt_addon"):
        return
    if getattr(ctx, "_plugin_wrapped", False):
        return
    orig = ctx.get_mood_prompt_addon

    def get_mood_prompt_addon(*a, **k):
        base = ""
        try:
            base = orig(*a, **k) or ""
        except Exception:
            base = ""
        extra_parts = []
        for p in packs:
            try:
                extra = _run_hook(p, "mood_addon", assistant)
                if extra:
                    extra_parts.append(str(extra).strip())
            except Exception as e:
                logger.debug("mood_addon %s: %s", getattr(p, "plugin_id", p), e)
        if not extra_parts:
            return base
        return (base + "\n" if base else "") + "\n".join(extra_parts)

    ctx.get_mood_prompt_addon = get_mood_prompt_addon
    ctx._plugin_wrapped = True


def install():
    """Патч LMAssistant.__init__ — один раз. Вызвать из main.py до создания ассистента."""
    global _attached
    if _attached:
        return
    try:
        import assistant_core as ac
    except Exception as e:
        logger.warning("plugin_loader.install: no assistant_core (%s)", e)
        return
    cls = getattr(ac, "LMAssistant", None)
    if cls is None:
        return
    if getattr(cls, "_plugins_installed", False):
        _attached = True
        return
    orig = cls.__init__

    def __init__(self, *args, **kwargs):
        orig(self, *args, **kwargs)
        try:
            attach(self)
        except Exception as e:
            logger.warning("plugin attach: %s", e)

    cls.__init__ = __init__
    cls._plugins_installed = True
    _attached = True
    logger.info("plugin_loader: LMAssistant.__init__ wrapped")
