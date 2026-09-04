# -*- coding: utf-8 -*-
from PyQt5 import QtWidgets
from settings_ui import MainTabMixin, PluginsTabMixin, PersonaTabMixin
from settings_manager import save_settings, apply_to_config
import config


class SettingsDialog(MainTabMixin, PluginsTabMixin, PersonaTabMixin, QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки ассистента")
        self.resize(640, 740)
        self._persona_tab_widget = None
        self._custom_plugin_uis = {}
        self.tabs = QtWidgets.QTabWidget()

        main = QtWidgets.QWidget()
        self._setup_main_tab(main)
        self.tabs.addTab(main, "Основные")

        if self._has_characters():
            self._add_persona_tab()

        plug = QtWidgets.QWidget()
        self._setup_plugins_hub_tab(plug)
        self.tabs.addTab(plug, "Плагины")

        try:
            from plugin_catalog import list_plugins_meta
            for meta in list_plugins_meta():
                if (meta.get("settings_tab") or "") != "own":
                    continue
                own = QtWidgets.QWidget()
                if not self._try_plugin_custom_tab(own, meta):
                    self._setup_plugin_own_tab(own, meta)
                title = meta.get("settings_tab_title") or meta.get("name") or meta.get("id")
                self.tabs.addTab(own, str(title))
        except Exception as e:
            print("plugins own tabs:", e)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.tabs)
        row = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Сохранить")
        save_btn.clicked.connect(self._save)
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(save_btn)
        row.addWidget(close_btn)
        lay.addLayout(row)

        self.load_main_settings()
        if self._persona_tab_widget is not None:
            self.load_persona_settings()

    def _has_characters(self) -> bool:
        try:
            from character_catalog import list_character_ids
            return len(list_character_ids()) > 0
        except Exception:
            return False

    def _add_persona_tab(self) -> None:
        if self._persona_tab_widget is not None:
            return
        w = QtWidgets.QWidget()
        self._setup_persona_tab(w)
        self.tabs.insertTab(1, w, "🎭 Персонаж")
        self._persona_tab_widget = w

    def _try_plugin_custom_tab(self, tab, meta) -> bool:
        """Кастомный UI плагина (например список памяти)."""
        try:
            import importlib
            pid = meta.get("id")
            if not pid:
                return False
            parent = self.parent()
            engine = getattr(parent, "engine", None) if parent is not None else None
            app = getattr(engine, "app", None) if engine is not None else None
            target = None
            if app is not None:
                target = app.plugins.get(pid)
            if target is None:
                mod = importlib.import_module(f"plugins.{pid}.plugin")
                cls = getattr(mod, "PluginImpl", None)
                if cls is None:
                    return False
                target = cls()
            if app is None:
                from core.plugin_api import AppContext
                app = AppContext(config)
            if not hasattr(target, "setup_settings_tab"):
                return False
            ok = bool(target.setup_settings_tab(tab, app))
            if ok:
                self._custom_plugin_uis[pid] = target
            return ok
        except Exception as e:
            print(f"custom tab {meta.get('id')}: {e}")
            return False

    def _save(self):
        data = {}
        data.update(self.collect_main_settings())
        if self._persona_tab_widget is not None:
            data.update(self.collect_persona_settings())
        data.update(self.collect_plugins_settings())
        for pid, pl in self._custom_plugin_uis.items():
            try:
                extra = pl.collect_settings_tab() or {}
                if extra:
                    store = data.setdefault("PLUGIN_SETTINGS", {})
                    block = dict(store.get(pid) or {})
                    block.update(extra)
                    store[pid] = block
            except Exception as e:
                print(f"collect custom {pid}: {e}")
        prev = getattr(config, "ACTIVE_CHARACTER", "default")
        save_settings(data)
        apply_to_config(config)
        new_ch = getattr(config, "ACTIVE_CHARACTER", prev)
        parent = self.parent()
        engine = getattr(parent, "engine", None) if parent is not None else None
        app_ctx = getattr(engine, "app", None) if engine is not None else None
        if app_ctx is not None and hasattr(app_ctx, "set_active_character"):
            if str(new_ch) != str(prev):
                setattr(config, "ACTIVE_CHARACTER", prev)
                app_ctx.set_active_character(str(new_ch))
                setattr(config, "ACTIVE_CHARACTER", str(new_ch))
        QtWidgets.QMessageBox.information(self, "OK", "Сохранено.")
        self.accept()
