# -*- coding: utf-8 -*-
"""Главное окно ядра — тёмный стиль как раньше."""
from __future__ import annotations

from PyQt5 import QtWidgets, QtCore, QtGui
from qasync import asyncSlot
import config
from settings_dialog import SettingsDialog

try:
    from ui.theme import WINDOW_QSS
except Exception:
    WINDOW_QSS = """
    QMainWindow { background-color: #1e1e1e; }
    QPlainTextEdit, QTextBrowser { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; border-radius: 6px; }
    QLineEdit { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; padding: 8px; border-radius: 6px; }
    QPushButton { background-color: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 6px 10px; border-radius: 5px; }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton:disabled { background-color: #2a2a2a; color: #777; }
    QLabel { color: #ccc; }
    """


class ChatWindow(QtWidgets.QMainWindow):
    def __init__(self, engine, loader):
        super().__init__()
        self.engine = engine
        self.loader = loader
        self.setWindowTitle(getattr(config, "WINDOW_TITLE", "Лисичка — ядро"))
        self.resize(int(getattr(config, "WINDOW_WIDTH", 780)), int(getattr(config, "WINDOW_HEIGHT", 700)))
        self.setStyleSheet(WINDOW_QSS)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # верхняя полоска
        top = QtWidgets.QHBoxLayout()
        self.title_lab = QtWidgets.QLabel("🦊 Ассистент — ядро")
        self.title_lab.setStyleSheet("color: #f0c27a; font-size: 16px; font-weight: bold;")
        top.addWidget(self.title_lab)
        top.addStretch(1)
        self.status_dot = QtWidgets.QLabel("●")
        self.status_dot.setStyleSheet("color: #0f0; font-size: 14px;")
        self.status_text = QtWidgets.QLabel("готово")
        self.status_text.setStyleSheet("color: #aaa;")
        top.addWidget(self.status_dot)
        top.addWidget(self.status_text)
        layout.addLayout(top)

        self.chat = QtWidgets.QPlainTextEdit()
        self.chat.setReadOnly(True)
        font = QtGui.QFont("Segoe UI", 11)
        self.chat.setFont(font)
        layout.addWidget(self.chat, 1)

        row = QtWidgets.QHBoxLayout()
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Сообщение… Enter — отправить")
        self.input.returnPressed.connect(self._on_send)
        self.send_btn = QtWidgets.QPushButton("Отправить")
        self.send_btn.clicked.connect(self._on_send)
        self.settings_btn = QtWidgets.QPushButton("⚙ Настройки")
        self.settings_btn.clicked.connect(self._open_settings)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        row.addWidget(self.settings_btn)
        layout.addLayout(row)

        plugs = ", ".join(engine.app.plugins.keys()) or "нет"
        self.footer = QtWidgets.QLabel(f"Плагины: {plugs}  |  {getattr(config, 'API_URL', '')}")
        self.footer.setStyleSheet("color: #777; font-size: 11px;")
        layout.addWidget(self.footer)

        self._append_sys("Ядро запущено. Подключение: " + str(getattr(config, "API_URL", "")))

    def set_status(self, mode: str, text: str = "") -> None:
        colors = {
            "idle": "#0f0", "thinking": "#ff0", "error": "#f44", "offline": "#888",
        }
        self.status_dot.setStyleSheet(f"color: {colors.get(mode, '#0f0')}; font-size: 14px;")
        self.status_text.setText(text or mode)

    def _append_sys(self, text: str) -> None:
        self.chat.appendPlainText(f"• {text}\n")

    def _append(self, who: str, text: str) -> None:
        self.chat.appendPlainText(f"{who}\n{text}\n")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec_():
            self.footer.setText(
                f"Плагины: {', '.join(self.engine.app.plugins.keys()) or 'нет'}  |  {getattr(config, 'API_URL', '')}"
            )
            # обновить LLM client
            try:
                from core.llm_client import LLMClient
                self.engine.llm = LLMClient.from_config(config)
                self.engine.app.llm = self.engine.llm
                self.engine.system_prompt = getattr(config, "SYSTEM_PROMPT", self.engine.system_prompt)
            except Exception:
                pass

    @asyncSlot()
    async def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("Вы", text)
        self.send_btn.setEnabled(False)
        self.set_status("thinking", "думаю…")
        buf = []
        try:
            async for chunk in self.engine.handle_user(text):
                buf.append(chunk)
            reply = "".join(buf).strip() or "(пустой ответ)"
            self._append("Ассистент", reply)
            self.set_status("idle", "готово")
        except Exception as e:
            self._append("Ошибка", str(e))
            self.set_status("error", "ошибка")
        finally:
            self.send_btn.setEnabled(True)

    def closeEvent(self, event) -> None:
        try:
            if self.loader:
                self.loader.shutdown_all()
        except Exception:
            pass
        event.accept()
