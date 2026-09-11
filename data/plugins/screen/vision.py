# -*- coding: utf-8 -*-
"""Видение экрана: снимок выбранного монитора (с понятными именами как в Windows)."""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.plugin_api import AppContext, Plugin, SettingField


def list_monitors() -> List[Dict[str, Any]]:
    """
    Список мониторов:
      index 0 = виртуальный «все экраны»
      1..N   = физические (как в mss / близко к нумерации Windows)
    """
    out: List[Dict[str, Any]] = []
    try:
        import mss
        with mss.mss() as sct:
            # sct.monitors[0] = bounding box all
            all_m = sct.monitors[0]
            out.append({
                "index": 0,
                "label": f"0 — Все экраны сразу ({all_m['width']}×{all_m['height']})",
                "width": all_m["width"],
                "height": all_m["height"],
                "left": all_m["left"],
                "top": all_m["top"],
                "primary": False,
            })
            for i, m in enumerate(sct.monitors[1:], start=1):
                primary = (m.get("left", 0) == 0 and m.get("top", 0) == 0)
                # primary heuristic: often monitor 1 is primary; also left=0 top=0
                tag = "основной" if primary or i == 1 else f"доп. #{i}"
                out.append({
                    "index": i,
                    "label": (
                        f"{i} — Монитор {i} ({tag}): "
                        f"{m['width']}×{m['height']} @ ({m['left']},{m['top']})"
                    ),
                    "width": m["width"],
                    "height": m["height"],
                    "left": m["left"],
                    "top": m["top"],
                    "primary": primary or i == 1,
                })
            # refine primary: smallest left+top among physical is usually primary in Windows
            if len(out) > 1:
                phys = out[1:]
                best = min(phys, key=lambda x: (x["left"] ** 2 + x["top"] ** 2, x["index"]))
                for m in phys:
                    m["primary"] = m["index"] == best["index"]
                    tag = "основной" if m["primary"] else f"доп. #{m['index']}"
                    m["label"] = (
                        f"{m['index']} — Монитор {m['index']} ({tag}): "
                        f"{m['width']}×{m['height']} @ ({m['left']},{m['top']})"
                    )
    except Exception as e:
        print(f"screen_vision: list_monitors: {e}", flush=True)
        out = [
            {"index": 0, "label": "0 — Все экраны", "width": 0, "height": 0, "left": 0, "top": 0, "primary": False},
            {"index": 1, "label": "1 — Монитор 1 (основной)", "width": 0, "height": 0, "left": 0, "top": 0, "primary": True},
            {"index": 2, "label": "2 — Монитор 2", "width": 0, "height": 0, "left": 0, "top": 0, "primary": False},
            {"index": 3, "label": "3 — Монитор 3", "width": 0, "height": 0, "left": 0, "top": 0, "primary": False},
        ]
    return out


class PluginImpl(Plugin):
    id = "screen_vision"
    name = "Видение экрана"
    version = "2.2.0"
    description = "Снимок выбранного монитора для описания"
    settings_tab = "own"
    settings_tab_title = "Видение экрана"
    # schema без monitor — монитор рисуем в custom UI
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("max_side", "Макс. сторона снимка (px)", "int", 1600, min_value=640, max_value=3840),
        SettingField("monitor", "Индекс монитора", "int", 1, min_value=0, max_value=8,
                     help="Служебное; выбирай в списке ниже"),
    ]

    def __init__(self) -> None:
        self._ui: Dict[str, Any] = {}
        self.app = None

    def register_tools(self, app: AppContext) -> None:
        app.tools["describe_screen"] = self.tool_describe_screen

    def tool_describe_screen(self, app: AppContext, **kwargs) -> str:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return "Видение экрана выключено."
        path = self.capture(app)
        if not path:
            return "Не удалось сделать снимок (нужен Pillow / mss)."
        app.state["screen_vision_attach"] = True
        app.state["screen_vision_just_captured"] = True
        app.state["screen_vision_last_path"] = str(path)
        mon = self._monitor_index(app)
        info = next((m for m in list_monitors() if m["index"] == mon), None)
        label = info["label"] if info else str(mon)
        app.state["screen_vision_last_desc"] = f"screenshot:{path.name} | {label}"
        return f"Снимок готов: {label}"

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.state.pop("screen_vision_attach", None) and not app.state.get("screen_vision_just_captured"):
            return messages
        app.state["screen_vision_just_captured"] = False
        return messages

    def on_after_llm(self, reply: str, app: AppContext) -> str:
        text = reply or ""
        keys = self._keywords(text)
        if keys and not any(w in keys for w in ("день", "вечер", "утром", "лови", "ищу", "жми")):
            app.state["screen_vision_search_query"] = keys
            print(f"screen_vision: search_query={keys!r}", flush=True)
            if any(p in text.lower() for p in ("похож", "similar", "найти картин")):
                app.state["screen_vision_pending_similar"] = True
        return reply

    def _monitor_index(self, app: AppContext) -> int:
        raw = app.get_plugin_setting(self.id, "monitor", 1)
        try:
            return int(str(raw).split()[0])
        except Exception:
            return 1

    def capture(self, app: AppContext) -> Optional[Path]:
        try:
            from PIL import Image, ImageGrab
        except ImportError:
            return None
        mon_idx = self._monitor_index(app)
        try:
            image = None
            try:
                import mss
                with mss.mss() as sct:
                    if mon_idx <= 0:
                        mon = sct.monitors[0]
                    elif mon_idx < len(sct.monitors):
                        mon = sct.monitors[mon_idx]
                    else:
                        mon = sct.monitors[-1]
                    print(f"screen_vision: capture idx={mon_idx} geo={mon}", flush=True)
                    shot = sct.grab(mon)
                    image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            except Exception as e:
                print(f"screen_vision: mss fallback: {e}", flush=True)
                image = ImageGrab.grab(all_screens=(mon_idx <= 0))
            if image is None:
                return None
            max_side = int(app.get_plugin_setting(self.id, "max_side", 1600) or 1600)
            image.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=86)
            base = Path(getattr(app.config, "DATA_DIR", Path("data"))) / "cache"
            base.mkdir(parents=True, exist_ok=True)
            path = base / "screen_last.jpg"
            path.write_bytes(buf.getvalue())
            return path
        except Exception as e:
            print(f"screen_vision: {e}", flush=True)
            return None

    # ---- Settings UI ----
    def setup_settings_tab(self, tab, app: AppContext) -> bool:
        try:
            from PyQt5 import QtWidgets, QtCore
        except ImportError:
            return False
        self.app = app
        layout = tab.layout() or QtWidgets.QVBoxLayout(tab)
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        layout.addWidget(QtWidgets.QLabel(
            "<b>Видение экрана</b><br>"
            "Выбери монитор так же, как в параметрах Windows: "
            "по номеру, размеру и позиции (левый/верхний угол)."
        ))

        # enabled + max_side
        values = {}
        try:
            from plugin_catalog import plugin_settings_block
            values = plugin_settings_block(self.id) or {}
        except Exception:
            pass

        self._ui = {}
        en = QtWidgets.QCheckBox("Включить")
        en.setChecked(bool(values.get("enabled", True)))
        self._ui["enabled"] = en
        layout.addWidget(en)

        form = QtWidgets.QFormLayout()
        spin = QtWidgets.QSpinBox()
        spin.setRange(640, 3840)
        spin.setValue(int(values.get("max_side", 1600) or 1600))
        self._ui["max_side"] = spin
        form.addRow("Макс. сторона снимка (px)", spin)
        layout.addLayout(form)

        layout.addWidget(QtWidgets.QLabel("<b>Монитор для снимков и «что на экране»</b>"))
        combo = QtWidgets.QComboBox()
        monitors = list_monitors()
        cur = int(values.get("monitor", 1) or 1)
        sel = 0
        for i, m in enumerate(monitors):
            combo.addItem(m["label"], m["index"])
            if m["index"] == cur:
                sel = i
        combo.setCurrentIndex(sel)
        self._ui["monitor_combo"] = combo
        layout.addWidget(combo)

        info = QtWidgets.QLabel("")
        info.setWordWrap(True)
        layout.addWidget(info)

        def update_info():
            idx = combo.currentData()
            m = next((x for x in monitors if x["index"] == idx), None)
            if not m:
                info.setText("")
                return
            if m["index"] == 0:
                info.setText(
                    "Будет склеен <b>весь рабочий стол</b> (все мониторы). "
                    "Модель чаще путается — лучше выбрать один."
                )
            else:
                prim = "да" if m.get("primary") else "нет"
                info.setText(
                    f"Снимок только этого экрана.<br>"
                    f"Разрешение: <b>{m['width']}×{m['height']}</b><br>"
                    f"Позиция (лево, верх): <b>({m['left']}, {m['top']})</b><br>"
                    f"Основной в Windows (эвристика): <b>{prim}</b><br>"
                    f"<i>Подсказка: в Windows «Параметры → Система → Дисплей» номера "
                    f"часто совпадают с 1, 2, 3… Слева направо смотри left.</i>"
                )

        combo.currentIndexChanged.connect(lambda *_: update_info())
        update_info()

        # Identify: flash border by capturing and showing path + optional brief
        btn_row = QtWidgets.QHBoxLayout()
        btn_ref = QtWidgets.QPushButton("Обновить список мониторов")
        btn_test = QtWidgets.QPushButton("Тест: снимок выбранного")
        btn_row.addWidget(btn_ref)
        btn_row.addWidget(btn_test)
        layout.addLayout(btn_row)
        preview = QtWidgets.QLabel("(превью после теста)")
        preview.setAlignment(QtCore.Qt.AlignCenter)
        preview.setMinimumHeight(120)
        layout.addWidget(preview)
        self._ui["preview"] = preview

        def reload_list():
            combo.blockSignals(True)
            combo.clear()
            mons = list_monitors()
            cur_i = combo.currentData() if combo.count() else 1
            for m in mons:
                combo.addItem(m["label"], m["index"])
            # restore
            for i in range(combo.count()):
                if combo.itemData(i) == cur:
                    combo.setCurrentIndex(i)
                    break
            combo.blockSignals(False)
            update_info()

        def test_shot():
            # временно применить monitor из combo
            idx = combo.currentData()
            try:
                from plugin_catalog import set_plugin_setting
                set_plugin_setting(self.id, "monitor", int(idx))
            except Exception:
                # fallback app state
                if not hasattr(app.config, "PLUGIN_SETTINGS"):
                    app.config.PLUGIN_SETTINGS = {}
                app.config.PLUGIN_SETTINGS.setdefault(self.id, {})["monitor"] = int(idx)
            path = self.capture(app)
            if not path:
                preview.setText("Не удалось снять экран")
                return
            from PyQt5.QtGui import QPixmap
            pm = QPixmap(str(path))
            if not pm.isNull():
                preview.setPixmap(pm.scaledToWidth(320, QtCore.Qt.SmoothTransformation))
            else:
                preview.setText(str(path))
            QtWidgets.QMessageBox.information(
                tab, "Снимок",
                f"Сохранено: {path}\nМонитор: {combo.currentText()}",
            )

        btn_ref.clicked.connect(reload_list)
        btn_test.clicked.connect(test_shot)
        layout.addStretch(1)
        return True

    def collect_settings_tab(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if "enabled" in self._ui:
            out["enabled"] = self._ui["enabled"].isChecked()
        if "max_side" in self._ui:
            out["max_side"] = self._ui["max_side"].value()
        combo = self._ui.get("monitor_combo")
        if combo is not None:
            try:
                out["monitor"] = int(combo.currentData())
            except Exception:
                out["monitor"] = 1
        return out

    @staticmethod
    def _keywords(text: str) -> str:
        stop = {
            "на", "в", "и", "с", "что", "как", "это", "экран", "монитор", "вижу",
            "изображение", "картинка", "хозяин", "можно", "хочешь", "похожие",
            "день", "вечер", "утро", "лови", "ищу", "жми",
        }
        words = []
        for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", text or ""):
            lw = w.lower()
            if lw in stop:
                continue
            if lw not in words:
                words.append(lw)
            if len(words) >= 8:
                break
        return " ".join(words)


def register():
    return PluginImpl()
