# -*- coding: utf-8 -*-
"""Главное окно: чат с картинками (превью / полный экран) и вложениями."""
from __future__ import annotations

import html
import shutil
from datetime import datetime
from pathlib import Path

from PyQt5 import QtWidgets, QtCore, QtGui
from qasync import asyncSlot
import config
from settings_dialog import SettingsDialog

try:
    from ui.theme import WINDOW_QSS
except Exception:
    WINDOW_QSS = """
    QMainWindow { background-color: #1e1e1e; }
    QTextBrowser { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; border-radius: 6px; }
    QLineEdit { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; padding: 8px; border-radius: 6px; }
    QPushButton { background-color: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 6px 10px; border-radius: 5px; }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton:disabled { background-color: #2a2a2a; color: #777; }
    QLabel { color: #ccc; }
    """

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_TEXT_EXT = {".txt", ".md", ".json", ".csv", ".log", ".py", ".ini", ".yaml", ".yml"}


def attachments_root() -> Path:
    root = Path(__file__).resolve().parent / "attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXT


class FullscreenImage(QtWidgets.QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(path.name)
        self.setWindowState(QtCore.Qt.WindowMaximized)
        self.setStyleSheet("background:#111;")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self._path = path
        self._label = QtWidgets.QLabel()
        self._label.setAlignment(QtCore.Qt.AlignCenter)
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._label)
        btns = QtWidgets.QHBoxLayout()
        plus = QtWidgets.QPushButton("＋ крупнее")
        minus = QtWidgets.QPushButton("－ мельче")
        fit = QtWidgets.QPushButton("по экрану")
        close = QtWidgets.QPushButton("закрыть")
        plus.clicked.connect(lambda: self._zoom(1.25))
        minus.clicked.connect(lambda: self._zoom(0.8))
        fit.clicked.connect(self._fit)
        close.clicked.connect(self.accept)
        for b in (plus, minus, fit, close):
            btns.addWidget(b)
        lay.addLayout(btns)
        lay.addWidget(self._scroll, 1)
        self._pm = QtGui.QPixmap(str(path))
        self._scale = 1.0
        self._fit()

    def _apply(self):
        if self._pm.isNull():
            self._label.setText("не удалось открыть изображение")
            return
        w = max(40, int(self._pm.width() * self._scale))
        h = max(40, int(self._pm.height() * self._scale))
        scaled = self._pm.scaled(w, h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())

    def _fit(self):
        if self._pm.isNull():
            return
        avail = self._scroll.viewport().size()
        if avail.width() < 50 or avail.height() < 50:
            avail = QtCore.QSize(1200, 800)
        sx = avail.width() / max(1, self._pm.width())
        sy = avail.height() / max(1, self._pm.height())
        self._scale = min(sx, sy, 1.0)
        self._apply()

    def _zoom(self, factor: float):
        self._scale = max(0.1, min(6.0, self._scale * factor))
        self._apply()

    def mouseDoubleClickEvent(self, ev):
        self.accept()


class ChatWindow(QtWidgets.QMainWindow):
    def __init__(self, engine, loader):
        super().__init__()
        self.engine = engine
        self.loader = loader
        self._busy = False
        self._pending: list[Path] = []
        self.setWindowTitle(getattr(config, "WINDOW_TITLE", "Лисичка — ядро"))
        self.resize(int(getattr(config, "WINDOW_WIDTH", 780)), int(getattr(config, "WINDOW_HEIGHT", 700)))
        self.setStyleSheet(WINDOW_QSS)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

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

        self.chat = QtWidgets.QTextBrowser()
        self.chat.setReadOnly(True)
        self.chat.setOpenExternalLinks(False)
        self.chat.setOpenLinks(False)
        self.chat.anchorClicked.connect(self._on_anchor)
        self.chat.setFont(QtGui.QFont("Segoe UI", 11))
        layout.addWidget(self.chat, 1)

        self.attach_bar = QtWidgets.QLabel("")
        self.attach_bar.setStyleSheet("color:#9ad; font-size:12px;")
        self.attach_bar.setWordWrap(True)
        layout.addWidget(self.attach_bar)

        row = QtWidgets.QHBoxLayout()
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Сообщение… Enter — отправить")
        self.input.returnPressed.connect(self._on_send)
        self.attach_btn = QtWidgets.QPushButton("📎 Файл")
        self.attach_btn.setToolTip("Прикрепить картинку или файл для анализа")
        self.attach_btn.clicked.connect(self._attach)
        self.send_btn = QtWidgets.QPushButton("Отправить")
        self.send_btn.clicked.connect(self._on_send)
        self.voice_btn = QtWidgets.QPushButton("🎙 Голос")
        self.voice_btn.clicked.connect(self._toggle_voice)
        self.stop_speech_btn = QtWidgets.QPushButton("⏹ Стоп речь")
        self.stop_speech_btn.setToolTip("Остановить озвучивание ответа")
        self.stop_speech_btn.clicked.connect(self._stop_speech)
        self.settings_btn = QtWidgets.QPushButton("⚙ Настройки")
        self.settings_btn.clicked.connect(self._open_settings)
        row.addWidget(self.attach_btn)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        row.addWidget(self.voice_btn)
        row.addWidget(self.stop_speech_btn)
        row.addWidget(self.settings_btn)
        layout.addLayout(row)

        plugs = ", ".join(engine.app.plugins.keys()) or "нет"
        self.footer = QtWidgets.QLabel(f"Плагины: {plugs}  |  {getattr(config, 'API_URL', '')}")
        self.footer.setStyleSheet("color: #777; font-size: 11px;")
        layout.addWidget(self.footer)

        engine.app.state["gui"] = self
        try:
            engine.app.gui = self
        except Exception:
            pass
        self._append_sys("Ядро запущено. Подключение: " + str(getattr(config, "API_URL", "")))
        self._append_sys("Вложения: кнопка 📎. Картинка в чате — клик = на весь экран.")

    def attachments_dir(self) -> Path:
        day = attachments_root() / datetime.now().strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        return day

    def _refresh_attach_bar(self) -> None:
        if not self._pending:
            self.attach_bar.setText("")
            return
        names = ", ".join(p.name for p in self._pending)
        self.attach_bar.setText(f"Вложения ({len(self._pending)}): {names}")

    def _attach(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Файл для чата / анализа",
            "",
            "Все (*);;Картинки (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;Текст (*.txt *.md *.json *.csv *.py *.log)",
        )
        if not paths:
            return
        dest_dir = self.attachments_dir()
        for raw in paths:
            src = Path(raw)
            if not src.is_file():
                continue
            dest = dest_dir / src.name
            i = 1
            while dest.exists():
                dest = dest_dir / f"{src.stem}_{i}{src.suffix}"
                i += 1
            shutil.copy2(src, dest)
            self._pending.append(dest)
        self._refresh_attach_bar()
        self._append_sys(f"Скопировано в {dest_dir}: {len(paths)} файл(ов)")

    def _on_anchor(self, url: QtCore.QUrl) -> None:
        path = Path(url.toLocalFile() or "")
        if not path.exists():
            s = url.toString()
            if s.startswith("file:"):
                path = Path(url.toLocalFile())
        if path.exists() and _is_image(path):
            FullscreenImage(path, self).exec_()
        elif path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _html_text(self, text: str) -> str:
        return html.escape(text or "").replace("\n", "<br>")

    def _html_file(self, path: Path) -> str:
        uri = path.resolve().as_uri()
        name = html.escape(path.name)
        if _is_image(path):
            return (
                f'<div style="margin:6px 0;">'
                f'<a href="{uri}" title="открыть на весь экран">'
                f'<img src="{uri}" width="220" style="border-radius:8px; border:1px solid #555;" />'
                f"</a><br><span style='color:#888;font-size:11px;'>🖼 {name} — клик: полный экран</span></div>"
            )
        return (
            f'<div style="margin:6px 0;"><a href="{uri}" style="color:#9cf;">📄 {name}</a></div>'
        )

    def _append_html(self, block: str) -> None:
        self.chat.moveCursor(QtGui.QTextCursor.End)
        self.chat.insertHtml(block + "<br>")
        self.chat.moveCursor(QtGui.QTextCursor.End)

    def _append_sys(self, text: str) -> None:
        self._append_html(f'<span style="color:#888;">• {self._html_text(text)}</span>')

    def _append(self, who: str, text: str, files=None) -> None:
        color = "#f0c27a" if who == "Вы" else "#9ad7a0"
        if who == "Ошибка":
            color = "#f66"
        body = self._html_text(text)
        extra = ""
        for p in files or []:
            extra += self._html_file(Path(p))
        # auto-detect [фото: path] from plugins
        for m in __import__("re").findall(r"\[фото:\s*([^\]]+)\]", text or ""):
            fp = Path(m.strip())
            if fp.exists():
                extra += self._html_file(fp)
                body = body.replace(self._html_text(f"[фото: {m.strip()}]"), "")
        self._append_html(
            f'<div style="margin:8px 0 12px 0;"><b style="color:{color};">{html.escape(who)}</b><br>{body}{extra}</div>'
        )

    def publish_assistant_message(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._append("Ассистент", text)

    def submit_text(self, text: str) -> None:
        text = (text or "").strip()
        if text and not self._busy:
            self.input.setText(text)
            self._on_send()

    def _voice_plugin(self):
        return self.engine.app.plugins.get("voice") or self.engine.app.state.get("voice_plugin")

    def _toggle_voice(self) -> None:
        voice = self._voice_plugin()
        if voice is None:
            self._append_sys("Голосовой плагин не загружен.")
            return
        if getattr(voice, "_thread", None) is not None and voice._thread.is_alive():
            voice.stop_listening()
            self.voice_btn.setText("🎙 Голос")
            self._append_sys("Микрофон выключен.")
        else:
            voice.start_listening()
            self.voice_btn.setText("⏹ Стоп микрофон")
            self._append_sys("Микрофон включён.")

    def _stop_speech(self) -> None:
        voice = self._voice_plugin()
        if voice is None:
            self._append_sys("Голосовой плагин не загружен.")
            return
        if hasattr(voice, "stop_speaking"):
            voice.stop_speaking()
            self._append_sys("Озвучивание остановлено.")
        else:
            self._append_sys("В этой версии голоса нет stop_speaking — замените plugins/voice/plugin.py")

    def set_status(self, mode: str, text: str = "") -> None:
        colors = {"idle": "#0f0", "thinking": "#ff0", "error": "#f44", "offline": "#888"}
        self.status_dot.setStyleSheet(f"color: {colors.get(mode, '#0f0')}; font-size: 14px;")
        self.status_text.setText(text or mode)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec_():
            self.footer.setText(
                f"Плагины: {', '.join(self.engine.app.plugins.keys()) or 'нет'}  |  {getattr(config, 'API_URL', '')}"
            )
            try:
                from core.llm_client import LLMClient
                self.engine.llm = LLMClient.from_config(config)
                self.engine.app.llm = self.engine.llm
                self.engine.system_prompt = getattr(config, "SYSTEM_PROMPT", self.engine.system_prompt)
            except Exception:
                pass

    def _push_attachments_state(self, files):
        app = self.engine.app
        app.state["pending_attachments"] = [str(p) for p in files]
        app.state["last_attachments"] = [str(p) for p in files]

    @asyncSlot()
    async def _on_send(self) -> None:
        text = self.input.text().strip()
        files = list(self._pending)
        if not text and not files:
            return
        self.input.clear()
        self._pending.clear()
        self._refresh_attach_bar()
        self._append("Вы", text or "(вложение)", files)
        self._push_attachments_state(files)
        send_text = text
        if files:
            listed = ", ".join(Path(p).name for p in files)
            send_text = (text + "\n\n[ВЛОЖЕНИЯ: " + listed + "]").strip()
        self.send_btn.setEnabled(False)
        self._busy = True
        self.set_status("thinking", "думаю…")
        buf = []
        try:
            async for chunk in self.engine.handle_user(send_text):
                buf.append(chunk)
            reply = "".join(buf).strip() or "(пустой ответ)"
            self._append("Ассистент", reply)
            self.set_status("idle", "готово")
        except Exception as e:
            self._append("Ошибка", str(e))
            self.set_status("error", "ошибка")
        finally:
            self._busy = False
            self.send_btn.setEnabled(True)
            self.engine.app.state["pending_attachments"] = []

    def closeEvent(self, event) -> None:
        try:
            voice = self._voice_plugin()
            if voice is not None and hasattr(voice, "stop_speaking"):
                voice.stop_speaking()
        except Exception:
            pass
        try:
            if self.loader:
                self.loader.shutdown_all()
        except Exception:
            pass
        event.accept()
