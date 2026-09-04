# settings_ui/tab_main.py — Основные: LLM API
from PyQt5 import QtWidgets, QtCore
import json
import urllib.request
import config
from core.llm_client import normalize_api_url


class MainTabMixin:
    def _setup_main_tab(self, tab):
        layout = QtWidgets.QVBoxLayout(tab)

        layout.addWidget(QtWidgets.QLabel(
            "API URL — IP или localhost и порт. Примеры:\n"
            "http://127.0.0.1:1234/v1   или   http://192.168.0.10:1234"
        ))
        self.api_url_edit = QtWidgets.QLineEdit()
        self.api_url_edit.setPlaceholderText("http://127.0.0.1:1234/v1")
        layout.addWidget(self.api_url_edit)

        layout.addWidget(QtWidgets.QLabel("API Key (для LM Studio можно lm-studio):"))
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addWidget(self.api_key_edit)

        layout.addWidget(QtWidgets.QLabel("Модель (имя как в LM Studio):"))
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        layout.addWidget(self.model_combo)

        row = QtWidgets.QHBoxLayout()
        refresh_btn = QtWidgets.QPushButton("🔄 Обновить список моделей")
        refresh_btn.setToolTip("GET /v1/models у сервера")
        refresh_btn.clicked.connect(self.load_models_list)
        test_btn = QtWidgets.QPushButton("Проверить связь")
        test_btn.clicked.connect(self.test_connection)
        row.addWidget(refresh_btn)
        row.addWidget(test_btn)
        layout.addLayout(row)

        self.conn_status = QtWidgets.QLabel("")
        self.conn_status.setWordWrap(True)
        self.conn_status.setStyleSheet("color: #aaa;")
        layout.addWidget(self.conn_status)

        layout.addWidget(QtWidgets.QLabel("Temperature (0.0 – 2.0):"))
        self.temperature_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.temperature_edit)

        layout.addWidget(QtWidgets.QLabel("Max Tokens:"))
        self.max_tokens_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.max_tokens_edit)

        layout.addWidget(QtWidgets.QLabel("System prompt (ядро):"))
        self.system_edit = QtWidgets.QPlainTextEdit()
        self.system_edit.setMaximumHeight(120)
        layout.addWidget(self.system_edit)

        layout.addStretch()

    def _base_url(self) -> str:
        return normalize_api_url(self.api_url_edit.text().strip() or config.API_URL)

    def load_models_list(self):
        api_url = self._base_url()
        key = self.api_key_edit.text().strip() or getattr(config, "API_KEY", "lm-studio")
        self.conn_status.setText(f"Запрос моделей: {api_url}/models …")
        QtWidgets.QApplication.processEvents()
        errors = []
        names = []
        url = api_url.rstrip("/") + "/models"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = data.get("data") or data.get("models") or []
            for m in models:
                if isinstance(m, dict):
                    names.append(str(m.get("id") or m.get("name") or m))
                else:
                    names.append(str(m))
        except Exception as e:
            errors.append(f"{url}: {e}")

        current = self.model_combo.currentText().strip()
        if names:
            self.model_combo.clear()
            self.model_combo.addItems(names)
            if current:
                idx = self.model_combo.findText(current)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
                else:
                    self.model_combo.setEditText(current)
            self.conn_status.setStyleSheet("color: #0f0;")
            self.conn_status.setText(f"OK: моделей {len(names)}\n{api_url}")
        else:
            if self.model_combo.count() == 0:
                self.model_combo.addItem(
                    current or getattr(config, "MODEL_NAME", "local-model") or "local-model"
                )
            self.conn_status.setStyleSheet("color: #f66;")
            self.conn_status.setText(
                "Не удалось получить модели.\n" + "\n".join(errors[:4])
            )

    def test_connection(self):
        api_url = self._base_url()
        key = self.api_key_edit.text().strip() or "lm-studio"
        model = self.model_combo.currentText().strip() or "local-model"
        self.conn_status.setText("Тест chat/completions…")
        QtWidgets.QApplication.processEvents()
        url = api_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "stream": False,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            self.conn_status.setStyleSheet("color: #0f0;")
            self.conn_status.setText(f"Связь OK: {reply[:120]!r}")
        except Exception as e:
            self.conn_status.setStyleSheet("color: #f66;")
            self.conn_status.setText(f"Нет связи: {url}\n{e}")

    def load_main_settings(self) -> None:
        self.api_url_edit.setText(str(getattr(config, "API_URL", "")))
        self.api_key_edit.setText(str(getattr(config, "API_KEY", "")))
        self.model_combo.clear()
        self.model_combo.addItem(str(getattr(config, "MODEL_NAME", "") or "local-model"))
        self.temperature_edit.setText(str(getattr(config, "TEMPERATURE", 0.4)))
        self.max_tokens_edit.setText(str(getattr(config, "MAX_TOKENS", 1000)))
        self.system_edit.setPlainText(str(getattr(config, "SYSTEM_PROMPT", "") or ""))
        QtCore.QTimer.singleShot(300, self.load_models_list)

    def collect_main_settings(self) -> dict:
        try:
            temp = float(self.temperature_edit.text().strip().replace(",", ".") or "0.4")
        except ValueError:
            temp = 0.4
        try:
            tokens = int(self.max_tokens_edit.text().strip() or "1000")
        except ValueError:
            tokens = 1000
        return {
            "API_URL": normalize_api_url(self.api_url_edit.text().strip()),
            "API_KEY": self.api_key_edit.text().strip() or "lm-studio",
            "MODEL_NAME": self.model_combo.currentText().strip(),
            "TEMPERATURE": temp,
            "MAX_TOKENS": tokens,
            "SYSTEM_PROMPT": self.system_edit.toPlainText(),
        }
