# -*- coding: utf-8 -*-
"""Долговременная память: отдельная база на каждого персонажа."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt5 import QtWidgets, QtCore

from core.plugin_api import AppContext, HookResult, Plugin, SettingField
from plugins.memory.store import CharacterMemoryStore

_REMEMBER_RE = re.compile(
    r"(?i)^\s*(?:запомни|запомнить|remember)\s*(?:что\s*)?[:\-]?\s*(.+)$", re.S
)
_FORGET_RE = re.compile(
    r"(?i)^\s*(?:забудь|удали\s+память|forget)\s*(?:про\s+|about\s+)?(.+)$", re.S
)
_SHOW_RE = re.compile(
    r"(?i)^\s*(?:что\s+ты\s+помнишь|покажи\s+память|memory\s*list|вспомни\s+вс[её])\s*$"
)


class PluginImpl(Plugin):
    id = "memory"
    name = "Память персонажа"
    version = "1.3.0"
    description = "Своя долговременная память у каждого персонажа"
    settings_tab = "own"
    settings_tab_title = "Память"
    settings_schema = [
        SettingField("enabled", "Включить память", "bool", True),
        SettingField("inject_prompt", "Подмешивать в prompt", "bool", True),
        SettingField("search_limit", "Фактов в контекст", "int", 10, min_value=1, max_value=40),
        SettingField("max_prompt_chars", "Лимит символов в prompt", "int", 2500, min_value=200, max_value=12000),
        SettingField("auto_remember_user", "Авто «меня зовут / я живу»", "bool", True),
        SettingField("default_pinned", "Новые записи закреплять (долгосрочные)", "bool", True),
    ]

    def __init__(self):
        self.app: Optional[AppContext] = None
        self.store: Optional[CharacterMemoryStore] = None
        self._char_id: Optional[str] = None
        self._list: Optional[QtWidgets.QListWidget] = None
        self._edit: Optional[QtWidgets.QPlainTextEdit] = None
        self._cat: Optional[QtWidgets.QComboBox] = None
        self._key: Optional[QtWidgets.QLineEdit] = None
        self._pin: Optional[QtWidgets.QCheckBox] = None
        self._imp: Optional[QtWidgets.QDoubleSpinBox] = None
        self._status: Optional[QtWidgets.QLabel] = None
        self._char_label: Optional[QtWidgets.QLabel] = None
        self._enabled_cb: Optional[QtWidgets.QCheckBox] = None
        self._inject_cb: Optional[QtWidgets.QCheckBox] = None
        self._limit_spin: Optional[QtWidgets.QSpinBox] = None
        self._chars_spin: Optional[QtWidgets.QSpinBox] = None
        self._auto_cb: Optional[QtWidgets.QCheckBox] = None
        self._pin_new_cb: Optional[QtWidgets.QCheckBox] = None
        self._selected_id: Optional[int] = None

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state["memory_plugin"] = self
        app.state["persistent_memory"] = None
        if not app.get_plugin_setting(self.id, "enabled", True):
            print("🧠 memory: выключена", flush=True)
            return
        self._ensure_dirs_for_all()
        self._open_for(app.get_active_character())

    def on_shutdown(self, app: AppContext) -> None:
        self._close()

    def on_character_changed(self, character_id: str, previous_id: str, app: AppContext) -> None:
        self.app = app
        if not app.get_plugin_setting(self.id, "enabled", True):
            self._close()
            return
        self._open_for(character_id)
        if self._char_label is not None:
            self._char_label.setText(
                f"Персонаж: <b>{character_id}</b> — своя база, не общая"
            )
        if self._list is not None:
            self._refresh_list()

    def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        self._sync_character(app)
        if self.store is None:
            return HookResult(handled=True, reply="Память недоступна: нет папки персонажа.")
        t = (text or "").strip()
        if not t:
            return None

        if _SHOW_RE.match(t):
            items = self.store.list_all(limit=50)
            if not items:
                return HookResult(
                    handled=True,
                    reply=f"У «{self._char_id}» пока пустая долговременная память.",
                )
            lines = [f"Долговременная память «{self._char_id}»: {self.store.count()}"]
            for it in items:
                pin = "📌" if it.get("pinned") else "•"
                key = f" [{it['key']}]" if it.get("key") else ""
                lines.append(f"{pin} #{it['id']} ({it.get('category')}){key} {it.get('content')}")
            return HookResult(handled=True, reply="\n".join(lines))

        m = _REMEMBER_RE.match(t)
        if m:
            content = (m.group(1) or "").strip()
            if not content:
                return HookResult(handled=True, reply="Что запомнить?")
            pinned = bool(app.get_plugin_setting(self.id, "default_pinned", True))
            mid = self.store.add(content, category="longterm", importance=0.85, pinned=pinned)
            return HookResult(
                handled=True,
                reply=f"Записала в память «{self._char_id}» (#{mid}): {content}",
            )

        m = _FORGET_RE.match(t)
        if m:
            q = (m.group(1) or "").strip()
            if q.isdigit():
                ok = self.store.delete(int(q))
                return HookResult(handled=True, reply="Удалила." if ok else "Нет такой записи.")
            found = self.store.search(q, limit=10)
            if not found:
                return HookResult(handled=True, reply="Не нашла, что забыть.")
            for it in found:
                self.store.delete(int(it["id"]))
            return HookResult(handled=True, reply=f"Удалила записей: {len(found)}.")

        if app.get_plugin_setting(self.id, "auto_remember_user", True):
            self._maybe_auto_remember(t)
        return None

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not app.get_plugin_setting(self.id, "inject_prompt", True):
            return messages
        self._sync_character(app)
        if self.store is None or not messages:
            return messages
        user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = str(m.get("content") or "")
                break
        limit = int(app.get_plugin_setting(self.id, "search_limit", 10) or 10)
        max_chars = int(app.get_plugin_setting(self.id, "max_prompt_chars", 2500) or 2500)
        items = self.store.recall_for_prompt(user, limit=limit)
        block = self.store.format_for_prompt(items, max_chars=max_chars)
        if not block:
            return messages
        if messages[0].get("role") == "system":
            messages[0]["content"] = (messages[0].get("content") or "") + "\n\n" + block
        else:
            messages.insert(0, {"role": "system", "content": block})
        return messages

    def setup_settings_tab(self, tab, app: AppContext) -> bool:
        self.app = app
        self._sync_character(app)

        layout = QtWidgets.QVBoxLayout(tab)

        opts = QtWidgets.QGroupBox("Параметры")
        of = QtWidgets.QFormLayout(opts)
        self._enabled_cb = QtWidgets.QCheckBox()
        self._enabled_cb.setChecked(bool(app.get_plugin_setting(self.id, "enabled", True)))
        self._inject_cb = QtWidgets.QCheckBox()
        self._inject_cb.setChecked(bool(app.get_plugin_setting(self.id, "inject_prompt", True)))
        self._auto_cb = QtWidgets.QCheckBox()
        self._auto_cb.setChecked(bool(app.get_plugin_setting(self.id, "auto_remember_user", True)))
        self._pin_new_cb = QtWidgets.QCheckBox()
        self._pin_new_cb.setChecked(bool(app.get_plugin_setting(self.id, "default_pinned", True)))
        self._limit_spin = QtWidgets.QSpinBox()
        self._limit_spin.setRange(1, 40)
        self._limit_spin.setValue(int(app.get_plugin_setting(self.id, "search_limit", 10) or 10))
        self._chars_spin = QtWidgets.QSpinBox()
        self._chars_spin.setRange(200, 12000)
        self._chars_spin.setValue(int(app.get_plugin_setting(self.id, "max_prompt_chars", 2500) or 2500))
        of.addRow("Включить", self._enabled_cb)
        of.addRow("В prompt", self._inject_cb)
        of.addRow("Авто-факты", self._auto_cb)
        of.addRow("Новые = закреплённые", self._pin_new_cb)
        of.addRow("Фактов в контекст", self._limit_spin)
        of.addRow("Лимит символов", self._chars_spin)
        layout.addWidget(opts)

        char = app.get_active_character() if app else "?"
        self._char_label = QtWidgets.QLabel(
            f"Персонаж: <b>{char}</b> — своя база, не общая"
        )
        layout.addWidget(self._char_label)

        split = QtWidgets.QSplitter()
        self._list = QtWidgets.QListWidget()
        self._list.currentRowChanged.connect(self._on_select)
        split.addWidget(self._list)

        right = QtWidgets.QWidget()
        rf = QtWidgets.QVBoxLayout(right)
        self._edit = QtWidgets.QPlainTextEdit()
        rf.addWidget(self._edit, 1)
        form = QtWidgets.QFormLayout()
        self._cat = QtWidgets.QComboBox()
        self._cat.setEditable(True)
        self._cat.addItems(["longterm", "fact", "user", "preference", "pending_offer", "blocked_url"])
        self._key = QtWidgets.QLineEdit()
        self._pin = QtWidgets.QCheckBox("Закрепить (не терять приоритет)")
        self._imp = QtWidgets.QDoubleSpinBox()
        self._imp.setRange(0.0, 1.0)
        self._imp.setSingleStep(0.1)
        self._imp.setValue(0.7)
        form.addRow("Категория", self._cat)
        form.addRow("Ключ (опц.)", self._key)
        form.addRow(self._pin)
        form.addRow("Важность", self._imp)
        rf.addLayout(form)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)

        row = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("Добавить")
        b_add.clicked.connect(self._ui_add)
        b_save = QtWidgets.QPushButton("Сохранить правку")
        b_save.clicked.connect(self._ui_save)
        b_del = QtWidgets.QPushButton("Удалить")
        b_del.clicked.connect(self._ui_delete)
        b_ref = QtWidgets.QPushButton("Обновить список")
        b_ref.clicked.connect(self._refresh_list)
        row.addWidget(b_add)
        row.addWidget(b_save)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(b_ref)
        layout.addLayout(row)

        self._status = QtWidgets.QLabel("")
        self._status.setStyleSheet("color:#aaa;")
        layout.addWidget(self._status)

        self._refresh_list()
        return True

    def collect_settings_tab(self) -> Dict[str, Any]:
        if self._enabled_cb is None:
            return {}
        return {
            "enabled": self._enabled_cb.isChecked(),
            "inject_prompt": self._inject_cb.isChecked(),
            "auto_remember_user": self._auto_cb.isChecked(),
            "default_pinned": self._pin_new_cb.isChecked(),
            "search_limit": int(self._limit_spin.value()),
            "max_prompt_chars": int(self._chars_spin.value()),
        }

    def _refresh_list(self) -> None:
        if self._list is None:
            return
        self._list.clear()
        if self.app:
            self._sync_character(self.app)
        if self.store is None:
            if self._status:
                self._status.setText("Нет store — выберите персонажа / проверьте папку")
            return
        items = self.store.list_all(limit=500)
        for it in items:
            pin = "📌 " if it.get("pinned") else ""
            key = f" [{it['key']}]" if it.get("key") else ""
            text = f"{pin}#{it['id']} ({it.get('category')}){key} {it.get('content')}"
            if len(text) > 120:
                text = text[:117] + "…"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, int(it["id"]))
            self._list.addItem(item)
        if self._status:
            self._status.setText(f"«{self._char_id}»: {self.store.count()}  |  {self.store.db_path}")

    def _on_select(self, row: int) -> None:
        if row < 0 or self._list is None or self.store is None:
            self._selected_id = None
            return
        item = self._list.item(row)
        mid = item.data(QtCore.Qt.UserRole)
        self._selected_id = int(mid) if mid is not None else None
        data = self.store.get(self._selected_id) if self._selected_id else None
        if not data:
            return
        self._edit.setPlainText(data.get("content") or "")
        self._cat.setEditText(data.get("category") or "fact")
        self._key.setText(data.get("key") or "")
        self._pin.setChecked(bool(data.get("pinned")))
        self._imp.setValue(float(data.get("importance") or 0.5))

    def _ui_add(self) -> None:
        if self.app:
            self._sync_character(self.app)
        if self.store is None:
            return
        content = (self._edit.toPlainText() or "").strip()
        if not content:
            self._status.setText("Введите текст и нажмите Добавить")
            return
        mid = self.store.add(
            content,
            category=self._cat.currentText().strip() or "longterm",
            key=self._key.text().strip() or None,
            importance=float(self._imp.value()),
            pinned=self._pin.isChecked() or bool(
                self.app and self.app.get_plugin_setting(self.id, "default_pinned", True)
            ),
        )
        self._status.setText(f"Добавлено #{mid} в «{self._char_id}»")
        self._refresh_list()

    def _ui_save(self) -> None:
        if self.store is None or not self._selected_id:
            self._status.setText("Выберите запись в списке")
            return
        ok = self.store.update(
            self._selected_id,
            content=self._edit.toPlainText(),
            category=self._cat.currentText().strip() or "fact",
            key=self._key.text().strip() or None,
            importance=float(self._imp.value()),
            pinned=self._pin.isChecked(),
        )
        self._status.setText("Сохранено" if ok else "Ошибка")
        self._refresh_list()

    def _ui_delete(self) -> None:
        if self.store is None or not self._selected_id:
            return
        mid = self._selected_id
        if self.store.delete(mid):
            self._status.setText(f"Удалено #{mid}")
            self._selected_id = None
            self._edit.clear()
            self._refresh_list()

    def _sync_character(self, app: AppContext) -> None:
        cid = (app.get_active_character() or "").strip() or "default"
        if self.store is None or self._char_id != cid:
            self._open_for(cid)

    def _character_dir(self, character_id: str) -> Path:
        if self.app is not None and hasattr(self.app, "get_character_dir"):
            return Path(self.app.get_character_dir(character_id))
        try:
            from character_catalog import character_dir
            return Path(character_dir(character_id))
        except Exception:
            base = Path(getattr(self.app.config, "DATA_DIR", Path("."))) if self.app else Path(".")
            return base / "personas" / "characters" / character_id

    def _ensure_dirs_for_all(self) -> None:
        try:
            from character_catalog import list_character_ids, character_dir
            for cid in list_character_ids():
                mem = Path(character_dir(cid)) / "memory"
                mem.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"🧠 memory ensure dirs: {e}", flush=True)

    def _open_for(self, character_id: str) -> None:
        character_id = (character_id or "").strip() or "default"
        if self.store is not None and self._char_id == character_id:
            return
        self._close()
        if self.app is None:
            return
        cdir = self._character_dir(character_id)
        try:
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "memory").mkdir(parents=True, exist_ok=True)
            self.store = CharacterMemoryStore(cdir, character_id=character_id)
            self._char_id = character_id
            if self.app is not None:
                self.app.state["persistent_memory"] = self.store
            print(
                f"🧠 memory: {character_id} → {self.store.db_path} (n={self.store.count()})",
                flush=True,
            )
        except Exception as e:
            print(f"🧠 memory open: {e}", flush=True)
            self.store = None

    def _close(self) -> None:
        if self.store is not None:
            try:
                self.store.close()
            except Exception:
                pass
        self.store = None
        self._char_id = None

    def _maybe_auto_remember(self, text: str) -> None:
        if self.store is None:
            return
        patterns = [
            (r"(?i)меня\s+зовут\s+([A-Za-zА-Яа-яЁё0-9_\- ]{2,40})", "user_name"),
            (r"(?i)мо[ёе]\s+имя\s+([A-Za-zА-Яа-яЁё0-9_\- ]{2,40})", "user_name"),
            (r"(?i)я\s+живу\s+в\s+([A-Za-zА-Яа-яЁё0-9_\- ,]{2,60})", "user_city"),
            (r"(?i)мой\s+город\s+([A-Za-zА-Яа-яЁё0-9_\- ,]{2,60})", "user_city"),
            (r"(?i)мне\s+(\d{1,3})\s+лет", "user_age"),
        ]
        for pat, key in patterns:
            m = re.search(pat, text)
            if m:
                self.store.add(
                    m.group(1).strip(),
                    category="user",
                    key=key,
                    importance=0.9,
                    pinned=True,
                )
