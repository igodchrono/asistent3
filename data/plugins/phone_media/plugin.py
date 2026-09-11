# -*- coding: utf-8 -*-
"""Генератор картинок: промпт → подтверждение → выбор workflow (qwen/sdxl/z) → ComfyUI.

Референс: вложение 📎 или последнее изображение в чате (img2img, если в графе есть LoadImage).
"""
from __future__ import annotations

import copy
import json
import mimetypes
import random
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from core.plugin_api import AppContext, HookResult, Plugin, SettingField

_BLOCK = (
    "child", "children", "kid", "teen", "underage", "lolita", "loli", "shota",
    "minor", "школьн", "ребён", "ребен", "детск", "малолет",
)
_ASK = (
    "сгенерируй", "нарисуй", "сделай картин", "сделай изображ",
    "сгенери изображение", "сгенерируй изображение", "сгенерируй картин",
    "пришли фот", "скинь фот", "пришли фото", "нарисуй мне",
)
_ALIASES = {
    "qwen": "workflows/qwen_image.json",
    "кви": "workflows/qwen_image.json",
    "qwen_image": "workflows/qwen_image.json",
    "sdxl": "workflows/sdxl.json",
    "sd": "workflows/sdxl.json",
    "сдхл": "workflows/sdxl.json",
    "сд": "workflows/sdxl.json",
    "z": "workflows/z_image.json",
    "zimage": "workflows/z_image.json",
    "z-image": "workflows/z_image.json",
    "з": "workflows/z_image.json",
    "qwen_edit": "workflows/qwen_edit.json",
    "квинедит": "workflows/qwen_edit.json",
    "edit": "workflows/qwen_edit.json",
    "правка": "workflows/qwen_edit.json",
}


class PluginImpl(Plugin):
    id = "phone_media"
    name = "Генератор картинок"
    version = "5.0.0"
    description = "Промпт → ок? → qwen/sdxl/z → ComfyUI"
    settings_tab = "own"
    settings_tab_title = "Генератор"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("comfy_url", "ComfyUI", "str", "http://127.0.0.1:8188"),
        SettingField("timeout_sec", "Таймаут сек", "int", 900, min_value=60, max_value=900),
        SettingField("steps", "Steps (если есть KSampler)", "int", 8, min_value=4, max_value=60),
        SettingField("width", "Ширина latent", "int", 1088, min_value=512, max_value=2048),
        SettingField("height", "Высота latent", "int", 1808, min_value=512, max_value=2048),
        SettingField("positive_prefix", "Префикс промпта", "str", "masterpiece, best quality, anime"),
        SettingField("default_workflow", "Workflow по умолчанию", "str", "qwen"),
        SettingField("ask_workflow", "Спрашивать движок каждый раз", "bool", True),
    ]

    def __init__(self):
        self.app = None
        self._ui: Dict[str, Any] = {}
        self._busy = False

    def on_load(self, app: AppContext) -> None:
        self.app = app
        app.state.setdefault("imggen_stage", "idle")
        print("🖼 imggen 5.0: prompt → confirm → workflow → ComfyUI", flush=True)

    def register_tools(self, app: AppContext) -> None:
        app.tools["generate_image"] = self.tool_generate

    def setup_settings_tab(self, tab, app: AppContext) -> bool:
        from PyQt5 import QtWidgets
        lay = QtWidgets.QVBoxLayout(tab)
        en = QtWidgets.QCheckBox("Включить генератор")
        en.setChecked(bool(app.get_plugin_setting(self.id, "enabled", True)))
        ask = QtWidgets.QCheckBox("Спрашивать Qwen / SDXL / Z каждый раз")
        ask.setChecked(bool(app.get_plugin_setting(self.id, "ask_workflow", True)))
        lay.addWidget(en)
        lay.addWidget(ask)
        url = QtWidgets.QLineEdit(str(app.get_plugin_setting(self.id, "comfy_url", "http://127.0.0.1:8188")))
        pref = QtWidgets.QLineEdit(str(app.get_plugin_setting(self.id, "positive_prefix", "masterpiece, best quality, anime")))
        dflt = QtWidgets.QComboBox()
        dflt.setEditable(True)
        for n in ("qwen", "sdxl", "z"):
            dflt.addItem(n)
        dflt.setEditText(str(app.get_plugin_setting(self.id, "default_workflow", "qwen")))
        tout = QtWidgets.QSpinBox(); tout.setRange(60, 900)
        tout.setValue(int(app.get_plugin_setting(self.id, "timeout_sec", 900) or 900))
        form = QtWidgets.QFormLayout()
        form.addRow("ComfyUI", url)
        form.addRow("Префикс промпта", pref)
        form.addRow("По умолчанию", dflt)
        form.addRow("Ждать сек", tout)
        lay.addLayout(form)
        lay.addWidget(QtWidgets.QLabel("Файлы в plugins/phone_media/workflows/:\nqwen_image.json, sdxl.json, z_image.json"))
        self._ui = dict(enabled=en, ask_workflow=ask, comfy_url=url, positive_prefix=pref,
                        default_workflow=dflt, timeout_sec=tout)
        lay.addStretch(1)
        return True

    def collect_settings_tab(self) -> Dict[str, Any]:
        u = self._ui
        return {
            "enabled": u["enabled"].isChecked(),
            "ask_workflow": u["ask_workflow"].isChecked(),
            "comfy_url": u["comfy_url"].text().strip(),
            "positive_prefix": u["positive_prefix"].text().strip(),
            "default_workflow": u["default_workflow"].currentText().strip() or "qwen",
            "timeout_sec": int(u["timeout_sec"].value()),
        }

    def on_user_message(self, text, app):
        if not app.get_plugin_setting(self.id, "enabled", True):
            return None
        low = (text or "").strip().lower()
        if not low:
            return None
        stage = str(app.state.get("imggen_stage") or "idle")

        if stage == "confirm":
            return self._handle_confirm(app, text, low)
        if stage == "busy":
            if any(w in low for w in ("отмена", "стоп генерац", "не надо картин")):
                app.state["imggen_stage"] = "idle"
                return HookResult(True, "ок, не жду эту картинку. можно просить новую.")
            return None

        if any(k in low for k in _ASK):
            refs = self._refs(app)
            app.state["imggen_request"] = text
            app.state["imggen_refs"] = refs
            app.state["imggen_stage"] = "confirm"
            card = self._llm_prompts_then_card(app, text, refs)
            return HookResult(True, card)
        return None

    def _handle_confirm(self, app, text, low):
        if any(w in low for w in ("нет", "не то", "другой промпт", "переделай промпт", "не подойд")):
            if len(low) > 12 and not low.startswith("нет"):
                refs = list(app.state.get("imggen_refs") or [])
                return HookResult(True, self._llm_prompts_then_card(app, text, refs))
            app.state["imggen_stage"] = "idle"
            return HookResult(True, "ок, без картинки. скажи заново, что нарисовать.")
        wf = self._pick_workflow_name(low)
        yes = any(w in low for w in ("да", "давай", "ок", "го", "пойдёт", "пойдет", "норм", "утвержд"))
        if wf or yes:
            if not wf:
                wf = str(app.get_plugin_setting(self.id, "default_workflow", "qwen") or "qwen")
            path = self._resolve_wf(wf)
            if not path.exists():
                return HookResult(True, f"нет файла {path.name}. Положи API-json в workflows/ и повтори имя (qwen/sdxl/z).")
            app.state["imggen_stage"] = "busy"
            fam = self._family(wf or path.stem)
            key = {
                "qwen": "imggen_prompt_qwen",
                "qwen_edit": "imggen_prompt_qwen_edit",
                "sdxl": "imggen_prompt_sdxl",
                "z": "imggen_prompt_z",
            }.get(fam, "imggen_prompt")
            prompt = str(app.state.get(key) or app.state.get("imggen_prompt") or "")
            refs = list(app.state.get("imggen_refs") or [])
            if fam == "qwen_edit" and not refs:
                app.state["imggen_stage"] = "confirm"
                return HookResult(True, "для правки нужен референс. 📎 фото и снова «правка».")
            self._start(app, prompt, path, refs)
            extra = f", референс: {Path(refs[0]).name}" if refs else ""
            return HookResult(True, f"запустила {path.stem}{extra}. это минуты, пиши пока — пришлю, как будет.")
        # treat as prompt edit via LLM
        refs = list(app.state.get("imggen_refs") or [])
        req = str(app.state.get("imggen_request") or "") + " | правка: " + text
        return HookResult(True, "обновила через LLM.\n" + self._llm_prompts_then_card(app, req, refs))

    def _ask_card(self, app, prompt: str, refs: List[str]) -> str:
        if app.state.get("imggen_prompt_qwen"):
            return self._ask_card_ready(app, refs)
        req = str(app.state.get("imggen_request") or "")
        qwen = self._draft_prompt(app, req, "qwen")
        qedit = self._draft_prompt(app, req, "qwen_edit") if refs else ""
        sdxl = self._draft_prompt(app, req, "sdxl")
        zpr = self._draft_prompt(app, req, "z")
        ref = (
            f"\nРеференс: {Path(refs[0]).name}. Для правки кадра — «qwen_edit» / «правка»."
            if refs else
            "\nРеференса нет. Для правки фото: 📎 + «поправь …»."
        )
        lines = [
            "Собрала промпты под модели:",
            f"Qwen:\n«{qwen}»",
        ]
        if qedit:
            lines.append(f"Qwen-правка:\n«{qedit}»")
        lines.append(f"SDXL:\n«{sdxl}»")
        lines.append(f"Z-Image:\n«{zpr}»")
        lines.append(ref)
        lines.append("Пиши: «давай qwen» / «sdxl» / «z» / «правка» — или поправь текст сцены.")
        app.state["imggen_prompt_qwen"] = qwen
        app.state["imggen_prompt_qwen_edit"] = qedit
        app.state["imggen_prompt_sdxl"] = sdxl
        app.state["imggen_prompt_z"] = zpr
        return "\n\n".join(lines)

    def _pick_workflow_name(self, low: str) -> str:
        # longer keys first
        for k in sorted(_ALIASES, key=len, reverse=True):
            if k in low.split() or f" {k} " in f" {low} " or low.endswith(k) or low.startswith(k):
                return k
        return ""

    def _list_wf(self) -> List[Path]:
        base = Path(__file__).resolve().parent
        out = []
        for folder in (base / "workflows", base):
            if folder.is_dir():
                out.extend(sorted(folder.glob("*.json")))
        return out

    def _resolve_wf(self, name: str) -> Path:
        base = Path(__file__).resolve().parent
        key = (name or "").strip().lower()
        rel = _ALIASES.get(key, key)
        p = Path(rel)
        if not p.is_absolute():
            p = base / rel
        if p.exists():
            return p
        for f in self._list_wf():
            if f.stem.lower() in (key, key.replace(" ", "_")):
                return f
        return p

    def _family(self, name: str) -> str:
        n = (name or "").lower()
        if "edit" in n or "правк" in n:
            return "qwen_edit"
        if "qwen" in n or "кви" in n:
            return "qwen"
        if "sdxl" in n or n in ("sd", "сд", "сдхл"):
            return "sdxl"
        if n in ("z", "zimage", "z-image", "з") or "z_image" in n:
            return "z"
        return "qwen"


    def _char_look(self, app) -> str:
        name = ""
        try:
            name = str(getattr(app, "active_character", None) or app.state.get("active_character") or "")
        except Exception:
            name = ""
        look = ""
        try:
            card = Path(__file__).resolve().parents[2] / "personas" / "characters" / name / "card.md"
            if card.exists():
                look = card.read_text(encoding="utf-8", errors="ignore")[:800]
        except Exception:
            look = ""
        return name or "персонаж", look or self._look_qwen()

    def _llm_complete(self, app, system: str, user: str) -> str:
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        # разные ядра ассистента
        for attr in ("llm", "client", "chat_engine"):
            obj = getattr(app, attr, None)
            if obj is None:
                obj = (app.state or {}).get(attr)
            if obj is None:
                continue
            for meth in ("complete", "chat", "ask", "generate"):
                fn = getattr(obj, meth, None)
                if not callable(fn):
                    continue
                try:
                    out = fn(msgs)
                except TypeError:
                    try:
                        out = fn(system=system, user=user)
                    except TypeError:
                        try:
                            out = fn(user)
                        except Exception:
                            continue
                except Exception as e:
                    print(f"imggen llm {attr}.{meth}: {e}", flush=True)
                    continue
                if isinstance(out, dict):
                    out = out.get("content") or out.get("text") or ""
                if out:
                    return str(out)
        # openai-совместимый локальный
        try:
            url = str(app.state.get("llm_url") or "http://127.0.0.1:1234/v1/chat/completions")
            payload = {"messages": msgs, "temperature": 0.4, "max_tokens": 700}
            raw = self._post(url, payload, timeout=90)
            ch = (raw.get("choices") or [{}])[0]
            return str((ch.get("message") or {}).get("content") or "")
        except Exception as e:
            print(f"imggen llm http: {e}", flush=True)
            return ""

    def _parse_prompt_json(self, raw: str) -> dict:
        s = (raw or "").strip()
        if "```" in s:
            s = s.split("```", 2)[1]
            if s.lower().startswith("json"):
                s = s[4:]
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            s = s[i:j+1]
        try:
            data = json.loads(s)
            if isinstance(data, dict):
                return {k: str(v).strip() for k, v in data.items() if v}
        except Exception:
            pass
        return {}

    def _llm_prompts_then_card(self, app, request: str, refs: list) -> str:
        name, look = self._char_look(app)
        nsfw = False
        try:
            nsfw = bool(app.state.get("nsfw") or app.get_plugin_setting("persona", "nsfw", False))
        except Exception:
            pass
        system = (
            "Ты редактор промптов для генерации изображений. "
            "Пользователь описал сцену на русском. НЕ копируй его фразу целиком. "
            "Переведи сцену в нормальный визуальный промпт: поза, одежда, место, свет, ракурс. "
            "Персонаж всегда тот же. "
            "Верни ТОЛЬКО JSON без markdown:\n"
            '{"qwen":"...","sdxl":"...","z":"...","qwen_edit":"..."}\n'
            "qwen — 1–3 предложения естественным языком (RU или EN), детальная сцена.\n"
            "sdxl — теги через запятую, английский, без предложений.\n"
            "z — короткое английское описание + ключевые детали.\n"
            "qwen_edit — инструкция правки кадра (если есть референс), иначе пустая строка.\n"
            "Нельзя: дети, loli, школьницы. Нельзя писать 'на котором ты'."
        )
        user = (
            f"Персонаж: {name}\nВнешность/карточка:\n{look}\n"
            f"NSFW персонажа: {'да, взрослое кружевное бельё можно' if nsfw else 'умеренно, без явной анатомии'}\n"
            f"Референс приложен: {'да' if refs else 'нет'}\n"
            f"Запрос пользователя: {request}\n"
            "Собери три разных промпта под модели."
        )
        raw = self._llm_complete(app, system, user)
        data = self._parse_prompt_json(raw)
        print(f"imggen llm prompts keys={list(data.keys())} raw={raw[:180]!r}", flush=True)
        if not data.get("qwen"):
            # LLM не ответила — лучше сказать, чем совать сырую фразу
            if raw:
                data["qwen"] = raw.strip()[:600]
            else:
                return (
                    "не смогла получить промпт от LLM. проверь LM Studio "
                    "(http://127.0.0.1:1234) и повтори запрос."
                )
        if self._blocked(" ".join(data.values())):
            app.state["imggen_stage"] = "idle"
            return "Такое не рисую."
        app.state["imggen_prompt_qwen"] = data.get("qwen") or ""
        app.state["imggen_prompt_sdxl"] = data.get("sdxl") or data.get("qwen") or ""
        app.state["imggen_prompt_z"] = data.get("z") or data.get("qwen") or ""
        app.state["imggen_prompt_qwen_edit"] = data.get("qwen_edit") or ""
        app.state["imggen_prompt"] = data.get("qwen") or ""
        return self._ask_card_ready(app, refs)

    def _ask_card_ready(self, app, refs: list) -> str:
        qwen = str(app.state.get("imggen_prompt_qwen") or "")
        qedit = str(app.state.get("imggen_prompt_qwen_edit") or "")
        sdxl = str(app.state.get("imggen_prompt_sdxl") or "")
        zpr = str(app.state.get("imggen_prompt_z") or "")
        ref = (
            f"\nРеференс: {Path(refs[0]).name}. Для правки — «правка»."
            if refs else
            "\nРеференса нет. 📎 + «поправь …» если нужно img2img."
        )
        lines = [
            "LLM собрала промпты (не сырой запрос):",
            f"Qwen:\n«{qwen}»",
        ]
        if qedit:
            lines.append(f"Qwen-правка:\n«{qedit}»")
        lines.append(f"SDXL:\n«{sdxl}»")
        lines.append(f"Z-Image:\n«{zpr}»")
        lines.append(ref)
        lines.append("Если ок — «давай qwen» / «sdxl» / «z» / «правка». Если нет — опиши правку сцены.")
        return "\n\n".join(lines)

    def _user_scene(self, raw: str) -> str:

        extra = (raw or "").strip()
        for w in (
            "сгенерируй изображение", "сгенерируй картинку", "сгенерируй",
            "нарисуй мне", "нарисуй", "сделай картинку", "сделай изображение",
            "пришли фотку", "пришли фото", "скинь фотку", "скинь фото",
            "отредактируй", "поправь фото", "измени фото", "пожалуйста",
        ):
            extra = extra.replace(w, " ")
            extra = extra.replace(w.capitalize(), " ")
        return " ".join(extra.split())

    def _look_qwen(self) -> str:
        return (
            "аниме-девушка лиса: рыжие длинные волосы, лисьи уши, пушистый хвост, "
            "голубые глаза, узнаваемый персонаж Лисичка"
        )

    def _draft_prompt(self, app, raw: str, family: str = "") -> str:
        fam = family or str(app.state.get("imggen_family") or app.get_plugin_setting(self.id, "default_workflow", "qwen") or "qwen")
        fam = self._family(fam)
        scene = self._user_scene(raw)
        refs = bool(app.state.get("imggen_refs") or self._refs(app))
        if fam == "qwen_edit" or (fam == "qwen" and refs):
            if not scene:
                scene = "аккуратно отредактируй кадр, сохрани лицо и характер"
            return (
                "Отредактируй это изображение. Сохрани ту же героиню и композицию, "
                f"если не сказано иначе. Задача: {scene}. "
                "Стиль: аниме, чистое лицо, без водяных знаков."
            )
        if fam == "qwen":
            if not scene:
                scene = "стоит у окна и смотрит наружу, полный рост"
            return (
                f"Аниме-иллюстрация. {self._look_qwen()}. Сцена: {scene}. "
                "Качественный свет, цельные руки, без текста на картинке."
            )
        if fam == "sdxl":
            prefix = str(app.get_plugin_setting(self.id, "positive_prefix", "masterpiece, best quality, anime") or "")
            tags = "fox girl, orange long hair, fox ears, fluffy tail, blue eyes"
            sc = scene or "full body, looking out the window"
            return f"{prefix}, {tags}, {sc}, detailed background"
        # z-image: короче, почти как qwen, без sd-тегов
        if not scene:
            scene = "full body portrait by the window"
        return (
            f"anime fox girl with orange hair and tail, {scene}, "
            "clean lineart, high detail, no watermark"
        )

    def _blocked(self, q: str) -> bool:
        return any(w in (q or "").lower() for w in _BLOCK)

    def _refs(self, app) -> List[str]:
        files = list(app.state.get("pending_attachments") or []) + list(app.state.get("last_attachments") or [])
        last = app.state.get("phone_media_last")
        if last:
            files.append(last)
        out, seen = [], set()
        for f in files:
            p = Path(str(f))
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} and p.exists() and str(p) not in seen:
                seen.add(str(p))
                out.append(str(p))
        return out

    def _base(self, app) -> str:
        return str(app.get_plugin_setting(self.id, "comfy_url", "http://127.0.0.1:8188") or "").rstrip("/")

    def _start(self, app, prompt, wf_path: Path, refs: List[str]):
        def work():
            try:
                msg = self.tool_generate(app, prompt=prompt, workflow=str(wf_path), refs=refs)
            except Exception as e:
                msg = f"генерация сломалась: {e}"
            app.state["imggen_stage"] = "idle"
            path = app.state.get("phone_media_last")
            req = str(app.state.get("imggen_request") or "")
            ok = path and Path(str(path)).exists() and "ошиб" not in (msg or "").lower() and "не " not in (msg or "")[:18]
            if ok:
                msg = f"помнишь, ты просил «{req[:80]}»? вот кадр."
            self._notify(app, msg, path if ok else None)
        threading.Thread(target=work, name="imggen", daemon=True).start()

    def _notify(self, app, msg, path):
        def ui():
            gui = app.state.get("gui") or getattr(app, "gui", None)
            files = [Path(path)] if path and Path(str(path)).exists() else []
            if gui and hasattr(gui, "_append"):
                try:
                    gui._append("Ассистент", msg, files=files)
                    return
                except TypeError:
                    gui._append("Ассистент", msg + (f"\n[фото: {path}]" if files else ""))
        try:
            from PyQt5 import QtCore
            QtCore.QTimer.singleShot(0, ui)
        except Exception:
            ui()

    def _inbox(self) -> Path:
        return self._out_dir(self.app)

    def _out_dir(self, app) -> Path:
        name = "default"
        try:
            name = str(getattr(app, "active_character", None) or app.state.get("active_character") or "default")
        except Exception:
            pass
        # data/generated/<character>/
        root = Path(__file__).resolve().parents[2] / "generated" / name
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _load_graph(self, path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "prompt" in data and isinstance(data["prompt"], dict):
            data = data["prompt"]
        return copy.deepcopy(data)

    def _fill(self, app, graph: dict, prompt: str, refs: List[str]) -> dict:
        seed = random.randint(1, 2**31 - 1)
        w = int(app.get_plugin_setting(self.id, "width", 1088) or 1088)
        h = int(app.get_plugin_setting(self.id, "height", 1808) or 1808)
        steps = int(app.get_plugin_setting(self.id, "steps", 8) or 8)
        uploaded = None
        if refs:
            uploaded = self._upload(app, Path(refs[0]))
        for nid, node in graph.items():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type") or ""
            inp = node.setdefault("inputs", {})
            if ct == "CLIPTextEncode":
                meta = ((node.get("_meta") or {}).get("title") or "").lower()
                cur = str(inp.get("text") or "")
                is_pos = "positive" in meta or "PROMPT" in cur or nid == "4"
                is_neg = nid == "2" or "色调" in cur or ("negative" in meta)
                if is_pos:
                    inp["text"] = prompt
            if ct in ("EmptyLatentImage", "EmptySD3LatentImage"):
                inp["width"] = w
                inp["height"] = h
            if ct == "KSampler":
                inp["seed"] = seed
                inp["steps"] = steps
                if uploaded and refs:
                    # if latent comes from VAEEncode, don't force denoise 1
                    pass
            if ct == "LoadImage" and uploaded:
                inp["image"] = uploaded
        return graph

    def _upload(self, app, path: Path) -> Optional[str]:
        try:
            import uuid
            boundary = uuid.uuid4().hex
            data = path.read_bytes()
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                self._base(app) + "/upload/image",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
            name = resp.get("name") or path.name
            print(f"imggen: uploaded ref {name}", flush=True)
            return name
        except Exception as e:
            print(f"imggen: upload fail {e}", flush=True)
            return None

    def _post(self, url, payload, timeout=30):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))

    def _get(self, url, timeout=30):
        return urllib.request.urlopen(url, timeout=timeout).read()

    def tool_generate(self, app, prompt="", workflow="", refs=None, **kw):
        refs = refs or []
        path = Path(workflow) if workflow else self._resolve_wf(str(app.get_plugin_setting(self.id, "default_workflow", "qwen")))
        print(f"imggen: wf={path} prompt={prompt[:140]!r} refs={refs}", flush=True)
        try:
            graph = self._fill(app, self._load_graph(path), prompt, refs)
        except Exception as e:
            return f"не прочитан workflow: {e}"
        try:
            queued = self._post(self._base(app) + "/prompt", {"prompt": graph})
        except Exception as e:
            return f"ComfyUI /prompt: {e}"
        print(f"imggen: queue {queued}", flush=True)
        if queued.get("error") or queued.get("node_errors"):
            return f"граф отклонён: {queued.get('error') or queued.get('node_errors')}"
        pid = str(queued.get("prompt_id") or "")
        if not pid:
            return f"нет prompt_id: {queued}"
        limit = int(app.get_plugin_setting(self.id, "timeout_sec", 900) or 900)
        t0 = time.time()
        hist = {}
        n = 0
        while time.time() - t0 < limit:
            time.sleep(1.5)
            n += 1
            try:
                hist = json.loads(self._get(self._base(app) + "/history/" + pid).decode("utf-8"))
            except Exception:
                continue
            if pid in hist:
                break
            if n % 4 == 0:
                print(f"imggen: wait {int(time.time()-t0)}s", flush=True)
        else:
            return f"не успела за {limit} сек."
        outputs = (hist.get(pid) or {}).get("outputs") or {}
        info = None
        for node in outputs.values():
            if node.get("images"):
                info = node["images"][0]
                break
        if not info:
            return "в history нет картинки."
        q = "?filename=%s&subfolder=%s&type=%s" % (
            quote(str(info.get("filename") or ""), safe=""),
            quote(str(info.get("subfolder") or ""), safe=""),
            quote(str(info.get("type") or "output"), safe=""),
        )
        blob = self._get(self._base(app) + "/view" + q, timeout=120)
        dest = self._out_dir(app) / f"gen_{int(time.time())}.png"
        dest.write_bytes(blob)
        app.state["phone_media_last"] = str(dest)
        print(f"imggen: saved {dest}", flush=True)
        return f"[фото: {dest}]"


def register():
    return PluginImpl()
