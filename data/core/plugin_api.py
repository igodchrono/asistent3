# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

@dataclass
class HookResult:
    handled: bool = False
    reply: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SettingField:
    key: str
    label: str
    type: str = "bool"  # bool|int|float|str|choice
    default: Any = None
    choices: Optional[List[str]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    help: str = ""

class Plugin:
    id: str = "plugin"
    name: str = "Plugin"
    version: str = "1.0.0"
    description: str = ""
    settings_tab: str = "plugins"  # plugins | own
    settings_tab_title: str = ""
    settings_schema: List[SettingField] = []

    def get_settings_schema(self) -> List[SettingField]:
        return list(self.settings_schema or [])

    def setup_settings_tab(self, tab, app: "AppContext") -> bool:
        return False

    def collect_settings_tab(self) -> Dict[str, Any]:
        return {}

    def on_load(self, app: "AppContext") -> None:
        pass

    def on_shutdown(self, app: "AppContext") -> None:
        pass

    def on_user_message(self, text: str, app: "AppContext") -> Optional[HookResult]:
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: "AppContext") -> List[Dict[str, Any]]:
        return messages

    def on_after_llm(self, reply: str, app: "AppContext") -> str:
        return reply

    def on_character_changed(
        self, character_id: str, previous_id: str, app: "AppContext"
    ) -> None:
        """Активный персонаж сменился (ядро или настройки)."""

    def register_tools(self, app: "AppContext") -> None:
        pass

class AppContext:
    def __init__(self, config_mod: Any = None):
        self.config = config_mod
        self.llm = None
        self.plugins: Dict[str, Plugin] = {}
        self.tools: Dict[str, Callable] = {}
        self.state: Dict[str, Any] = {}
        self.window = None

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        if not getattr(self.config, "PLUGINS_ENABLED", True):
            return False
        m = getattr(self.config, "PLUGINS", None) or {}
        if not isinstance(m, dict) or plugin_id not in m:
            return True
        return bool(m.get(plugin_id))

    def get_plugin_setting(self, plugin_id: str, key: str, default: Any = None) -> Any:
        store = getattr(self.config, "PLUGIN_SETTINGS", None) or {}
        block = store.get(plugin_id) if isinstance(store, dict) else None
        if not isinstance(block, dict):
            return default
        return block.get(key, default)

    def register_tool(self, name: str, fn: Callable) -> None:
        self.tools[name] = fn

    def get_active_character(self) -> str:
        return str(
            getattr(self.config, "ACTIVE_CHARACTER", None)
            or "default"
        )

    def get_character_dir(self, character_id: str | None = None) -> "Path":
        from pathlib import Path
        cid = character_id or self.get_active_character()
        base = Path(getattr(self.config, "DATA_DIR", Path(".")))
        return base / "personas" / "characters" / cid

    def set_active_character(self, character_id: str) -> None:
        """Сменить персонажа и вызвать on_character_changed у плагинов."""
        character_id = (character_id or "").strip() or "default"
        prev = self.get_active_character()
        if character_id == prev:
            return
        setattr(self.config, "ACTIVE_CHARACTER", character_id)
        # уведомить плагины
        for pl in list(self.plugins.values()):
            try:
                pl.on_character_changed(character_id, prev, self)
            except Exception as e:
                print(f"[plugin {getattr(pl,'id', '?')}] on_character_changed: {e}", flush=True)
        print(f"🎭 character: {prev} → {character_id}", flush=True)
        # Обновить UI и связанные объекты без перезапуска: окно, движок, память и RAG
        try:
            win = getattr(self, 'window', None)
            if win is not None:
                try:
                    win.footer.setText(f"Плагины: {', '.join(self.plugins.keys()) or 'нет'}  |  {getattr(self.config, 'API_URL', '')}")
                except Exception:
                    pass
                try:
                    if hasattr(win, '_append_sys'):
                        win._append_sys(f"Персонаж: {prev} → {character_id}")
                except Exception:
                    pass

            # попытаться получить ChatEngine: сначала через окно, затем через state
            engine = None
            if win is not None and hasattr(win, 'engine'):
                engine = getattr(win, 'engine')
            if engine is None:
                engine = self.state.get('engine')

            # очистить историю движка, чтобы не смешивать контексты
            if engine is not None and hasattr(engine, 'history'):
                try:
                    engine.history.clear()
                except Exception:
                    try:
                        engine.history = []
                    except Exception:
                        pass

            # сбросить кэши карточек персонажей в модулях character_manager / character_catalog, если есть
            try:
                import character_manager as cm
                if hasattr(cm, 'invalidate_card_cache'):
                    try:
                        cm.invalidate_card_cache()
                    except Exception:
                        pass
                elif hasattr(cm, '_card_cache'):
                    try:
                        getattr(cm, '_card_cache', {}).clear()
                    except Exception:
                        pass
            except Exception:
                try:
                    import character_catalog as cc
                    if hasattr(cc, '_card_cache'):
                        try:
                            getattr(cc, '_card_cache', {}).clear()
                        except Exception:
                            pass
                except Exception:
                    pass

            # перезагрузить persistent memory и RAG, если они зарегистрированы в контексте
            # возможные места хранения: атрибуты объекта или self.state
            pm = getattr(self, 'persistent_memory', None) or self.state.get('persistent_memory')
            if pm is not None:
                for name in ('reload', 'reindex', 'rebuild', 'refresh', 'close', 'open'):
                    fn = getattr(pm, name, None)
                    if callable(fn):
                        try:
                            res = fn()
                            # если функция асинхронная — запустить
                            import asyncio
                            if hasattr(res, '__await__'):
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.ensure_future(res)
                                else:
                                    loop.run_until_complete(res)
                        except Exception:
                            pass

            # RAG: если есть, вызвать асинхронно prune + auto_index
            rag = getattr(self, 'rag', None) or self.state.get('rag')
            if rag is not None:
                try:
                    import asyncio

                    async def _reindex():
                        prune = getattr(rag, 'prune_inactive_personas_async', None)
                        if callable(prune):
                            try:
                                await prune()
                            except Exception:
                                pass
                        else:
                            p2 = getattr(rag, 'prune_inactive_personas', None)
                            if callable(p2):
                                try:
                                    p2()
                                except Exception:
                                    pass
                        auto = getattr(rag, 'auto_index_from_config_async', None)
                        if callable(auto):
                            try:
                                await auto()
                            except Exception:
                                pass
                        else:
                            a2 = getattr(rag, 'auto_index_from_config', None)
                            if callable(a2):
                                try:
                                    a2()
                                except Exception:
                                    pass

                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(_reindex())
                    else:
                        loop.run_until_complete(_reindex())
                except Exception as e:
                    print(f"RAG reload failed: {e}", flush=True)

        except Exception:
            pass
