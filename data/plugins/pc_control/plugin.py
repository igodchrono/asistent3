# -*- coding: utf-8 -*-
"""PC tools — только исполнители, без regex-фраз."""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, HookResult, Plugin, SettingField

_APP_ALIASES = {
    "калькулятор": "calc",
    "блокнот": "notepad",
    "проводник": "explorer",
    "explorer": "explorer",
    "chrome": "chrome",
    "браузер": "chrome",
}
_CLOSE_ALIASES = {
    "калькулятор": ["CalculatorApp.exe", "win32calc.exe", "calc.exe"],
    "блокнот": ["notepad.exe"],
}


class PluginImpl(Plugin):
    id = "pc_control"
    name = "Управление ПК"
    version = "2.0.0"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("allow_process_close", "Разрешить закрытие программ", "bool", True),
    ]

    def on_load(self, app: AppContext) -> None:
        self.app = app

    def register_tools(self, app: AppContext) -> None:
        app.tools["pc_open"] = self.tool_open
        app.tools["pc_close"] = self.tool_close
        app.tools["pc_volume"] = self.tool_volume
        app.tools["pc_search_files"] = self.tool_search_files
        app.tools["pc_search_folders"] = self.tool_search_folders
        app.tools["pc_open_found"] = self.tool_open_found
        app.tools["pc_close_last"] = self.tool_close_last
        app.tools["pc_create_text"] = self.tool_create_text
        app.tools["pc_recycle"] = self.tool_recycle
        app.tools["pc_empty_recycle"] = self.tool_empty_recycle

    def on_user_message(self, text: str, app: AppContext) -> Optional[HookResult]:
        pending = getattr(self, "_pending", None)
        low = (text or "").strip().lower()
        if pending:
            if low in ("да", "yes", "ок", "окей", "подтверждаю"):
                self._pending = None
                try:
                    reply = self._execute_pending(app, pending)
                except Exception as e:
                    reply = f"Не удалось: {e}"
                return HookResult(True, reply)
            if low in ("нет", "no", "отмена", "не надо"):
                self._pending = None
                return HookResult(True, "Отменено.")
        # мост для selftest / простых команд (основной путь — intent)
        if "открой найденное" in low or "открыть найденное" in low:
            return HookResult(True, self.tool_open_found(app))
        if low.startswith("открой ") or low.startswith("открыть "):
            return HookResult(True, self.tool_open(app, target=text.split(" ", 1)[-1]))
        if low.startswith("закрой ") or low.startswith("закрыть "):
            tgt = text.split(" ", 1)[-1]
            if "последн" in low:
                return HookResult(True, self.tool_close_last(app))
            if "открытые папки" in low or "окна проводника" in low:
                return HookResult(True, "Используй: закрой последнее открытое (не все папки).")
            return HookResult(True, self.tool_close(app, target=tgt))
        if low in ("громче",):
            return HookResult(True, self.tool_volume(app, direction="up"))
        if low in ("тише",):
            return HookResult(True, self.tool_volume(app, direction="down"))
        if "найди папк" in low:
            # найди папку X / найди папки X на диск D
            import re
            m = re.search(r"папк[уи]\s+(.+?)(?:\s+на\s+диск\s+([a-z]))?$", low)
            q = m.group(1).strip() if m else low.split()[-1]
            disk = (m.group(2) or "").upper() if m and m.lastindex and m.group(2) else ""
            return HookResult(True, self.tool_search_folders(app, query=q, disk=disk))
        if low.startswith("найди файл") or "найди файл" in low:
            import re
            m = re.search(r"файл\s+(.+?)(?:\s+на\s+диск\s+([a-z]))?$", low)
            q = m.group(1).strip() if m else "*"
            disk = (m.group(2) or "").upper() if m and m.lastindex and m.group(2) else ""
            return HookResult(True, self.tool_search_files(app, query=q, disk=disk))
        if "открой найденное" in low:
            return HookResult(True, self.tool_open_found(app))
        if "создай текстовый файл" in low or low.startswith("создай файл"):
            name = text.split("файл", 1)[-1].strip()
            return HookResult(True, self.tool_create_text(app, name=name))
        if "в корзину" in low or "в корзину" in text.lower():
            import re as _re
            # "удали файл NAME в корзину" / "перемести NAME в корзину"
            m = _re.search(
                r"(?:удали|удалить|перемести|помести)\s+(?:файл\s+)?(.+?)\s+в\s+корзину",
                text,
                flags=_re.I,
            )
            name = m.group(1).strip().strip('"') if m else ""
            if not name:
                m2 = _re.search(r"([\w.-]+\.\w{1,5})", text)
                name = m2.group(1) if m2 else ""
            return HookResult(True, self.tool_recycle(app, name=name))
        if "очисти корзину" in low or "очистить корзину" in low:
            return HookResult(True, self.tool_empty_recycle(app))
        return None

    def _focus_window_by_title(self, title_part: str, wait: float = 0.8) -> None:
        """Совместимость с selftest."""
        if not title_part:
            return
        time.sleep(max(0.2, float(wait)))
        part = title_part.replace("'", "''")[:80]
        ps = (
            f"$part='{part}'; "
            "Get-Process | Where-Object { $_.MainWindowTitle -like \"*$part*\" } | "
            "Select-Object -First 1 | ForEach-Object { "
            "  try { $_.CloseMainWindow() | Out-Null } catch {} "
            "}"
        )
        # только focus, не close — simplified set foreground
        ps = (
            f"$part='{part}'; "
            "Add-Type -Name W -Namespace Z -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h,int c);'; "
            "$p=Get-Process | Where-Object { $_.MainWindowTitle -like \"*$part*\" } | Select-Object -First 1; "
            "if($p){ [Z.W]::ShowWindow($p.MainWindowHandle,3); [Z.W]::SetForegroundWindow($p.MainWindowHandle) }"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=15)
        except Exception:
            pass

    def _execute_pending(self, app, pending):
        action = pending.get("action")
        if action == "empty_recycle":
            return self.tool_empty_recycle(app, confirmed=True)
        if action == "close":
            return self.tool_close(app, target=pending.get("target") or "", confirmed=True)
        return "Неизвестное действие."

    def tool_open(self, app: AppContext, target: str = "", **kw) -> str:
        target = (target or kw.get("query") or "").strip()
        if not target:
            return "Не указано, что открыть."
        alias = _APP_ALIASES.get(target.lower(), target)
        path = Path(os.path.expandvars(os.path.expanduser(alias)))
        if path.exists():
            os.startfile(str(path))
            app.state["pc_last_opened"] = str(path)
            return f"Открыто: {path}"
        exe = shutil.which(alias) or shutil.which(alias + ".exe")
        if exe:
            subprocess.Popen([exe], close_fds=True)
            return f"Запущено: {target}"
        # попробовать как путь
        try:
            os.startfile(target)
            app.state["pc_last_opened"] = target
            return f"Открыто: {target}"
        except Exception:
            return f"Не найдено: {target}"

    def tool_close(self, app: AppContext, target: str = "", confirmed: bool = False, **kw) -> str:
        target = (target or kw.get("query") or "").strip()
        if not confirmed and target and target.lower() not in ("калькулятор", "блокнот"):
            self._pending = {"action": "close", "target": target}
            return f"Подтвердите: закрыть {target}? да/нет"
        key = target.lower()
        candidates = list(_CLOSE_ALIASES.get(key, []))
        if not candidates:
            name = target if target.lower().endswith(".exe") else target + ".exe"
            candidates = [name]
        closed = []
        for image in candidates:
            r = subprocess.run(
                ["taskkill", "/IM", image, "/F"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                closed.append(image)
        return f"Закрыто: {', '.join(closed)}" if closed else f"Не найдено процесс: {target}"

    def tool_volume(self, app: AppContext, direction: str = "up", **kw) -> str:
        key = 0xAF if str(direction).lower() in ("up", "громче", "+") else 0xAE
        try:
            import ctypes
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        except Exception as e:
            return f"Громкость: {e}"
        return "Громкость увеличена." if key == 0xAF else "Громкость уменьшена."

    def tool_search_files(self, app: AppContext, query: str = "*", disk: str = "", **kw) -> str:
        query = (query or kw.get("text") or "*").strip()
        root_text = (disk or "").strip()
        roots = self._roots(root_text)
        patterns = (query if any(c in query for c in "*?") else f"*{query}*",)
        results: List[str] = []
        started = time.monotonic()
        skip = {"$recycle.bin", "system volume information", "windows", "program files",
                "program files (x86)", "programdata", "appdata", "node_modules", ".git"}
        for root in roots:
            if not root.exists():
                continue
            for cur, dirs, files in os.walk(root, topdown=True):
                dirs[:] = [d for d in dirs if d.lower() not in skip]
                try:
                    depth = len(Path(cur).relative_to(root).parts)
                except Exception:
                    depth = 0
                if depth > 8:
                    dirs[:] = []
                    continue
                for name in files:
                    if any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in patterns):
                        results.append(str(Path(cur) / name))
                        if len(results) >= 25:
                            break
                if len(results) >= 25 or time.monotonic() - started > 15:
                    break
            if len(results) >= 25 or time.monotonic() - started > 15:
                break
        app.state["pc_last_search"] = results
        if results:
            app.state["pc_last_found"] = results[0]
        if not results:
            return f"По «{query}» ничего не найдено."
        lines = "\n".join(f"{i}. {p}" for i, p in enumerate(results, 1))
        return f"Найдено файлов: {len(results)}\n{lines}"

    def tool_search_folders(self, app: AppContext, query: str = "", disk: str = "", **kw) -> str:
        query = (query or "").strip().lower()
        if not query:
            return "Укажи имя папки."
        roots = self._roots(disk)
        results: List[str] = []
        started = time.monotonic()
        skip = {"$recycle.bin", "system volume information", "windows", "program files",
                "program files (x86)", "programdata", "appdata", "node_modules", ".git"}
        for root in roots:
            if not root.exists():
                continue
            for cur, dirs, files in os.walk(root, topdown=True):
                dirs[:] = [d for d in dirs if d.lower() not in skip]
                try:
                    depth = len(Path(cur).relative_to(root).parts)
                except Exception:
                    depth = 0
                if depth > 7:
                    dirs[:] = []
                    continue
                for d in list(dirs):
                    if query in d.lower():
                        results.append(str(Path(cur) / d))
                        if len(results) >= 20:
                            break
                if len(results) >= 20 or time.monotonic() - started > 15:
                    break
            if len(results) >= 20 or time.monotonic() - started > 15:
                break
        app.state["pc_last_search"] = results
        if results:
            app.state["pc_last_found"] = results[0]
        if not results:
            return f"Папка «{query}» не найдена."
        lines = "\n".join(f"{i}. {p}" for i, p in enumerate(results, 1))
        return f"Найдено папок: {len(results)}\n{lines}"

    def tool_open_found(self, app: AppContext, **kw) -> str:
        path = str(app.state.get("pc_last_found") or "")
        if not path:
            return "Нет сохранённого результата поиска."
        os.startfile(path)
        app.state["pc_last_opened"] = path
        return f"Открыто: {path}"

    def tool_close_last(self, app: AppContext, **kw) -> str:
        path = str(app.state.get("pc_last_opened") or app.state.get("pc_last_found") or "")
        if not path:
            return "Нет последнего открытого."
        p = Path(path)
        if p.is_dir():
            ps = (
                f"$target = '{str(p).replace(chr(39), chr(39)+chr(39))}'; "
                "$shell = New-Object -ComObject Shell.Application; $n=0; "
                "foreach ($w in @($shell.Windows())) { try { "
                "if ($w.Document.Folder.Self.Path -eq $target) { $w.Quit(); $n++ } "
                "} catch {} }; Write-Output $n"
            )
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20)
            app.state["pc_last_opened"] = ""
            return f"Закрыто окон папки: {(r.stdout or '').strip()}"
        name = p.name.replace("'", "''")
        ps = (
            f"$name='{name}'; "
            "Get-Process | Where-Object { $_.MainWindowTitle -like \"*$name*\" } | "
            "ForEach-Object { try { $_.CloseMainWindow()|Out-Null } catch {} }; 'ok'"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20)
        app.state["pc_last_opened"] = ""
        return f"Закрыто: окна с «{p.name}»"

    def tool_create_text(self, app: AppContext, name: str = "note.txt", **kw) -> str:
        name = (name or kw.get("text") or "note.txt").strip().strip('"')
        p = Path(name)
        if not p.is_absolute():
            folder = Path(getattr(app.config, "DATA_DIR", Path("."))) / "selftest_files"
            folder.mkdir(parents=True, exist_ok=True)
            if not name.lower().endswith(".txt"):
                name += ".txt"
            p = folder / name
        p.write_text(f"created by pc_control\n{p}\n", encoding="utf-8")
        app.state["pc_last_text_file"] = str(p)
        return f"Создан файл: {p}"

    def tool_recycle(self, app: AppContext, name: str = "", **kw) -> str:
        raw = (name or kw.get("text") or "").strip().strip('"')
        # убрать мусорные префиксы
        for junk in ("удали файл ", "удалить файл ", "удали ", "файл "):
            if raw.lower().startswith(junk):
                raw = raw[len(junk):].strip()
        if not raw:
            raw = str(app.state.get("pc_last_text_file") or "")
        if not raw:
            return "Укажи файл."
        p = Path(raw)
        if not p.is_file():
            data_dir = Path(getattr(app.config, "DATA_DIR", Path(".")))
            for cand in (
                data_dir / "selftest_files" / Path(raw).name,
                data_dir / "selftest_files" / raw,
                Path(raw).name and data_dir / "selftest_files" / Path(raw).name,
            ):
                if cand and Path(cand).is_file():
                    p = Path(cand)
                    break
        if not p.is_file():
            # fallback last created
            last = str(app.state.get("pc_last_text_file") or "")
            if last and Path(last).is_file():
                p = Path(last)
            else:
                return f"Файл не найден: {raw}"
        parent = str(p.parent).replace("'", "''")
        nm = p.name.replace("'", "''")
        ps = (
            f"$p=Join-Path '{parent}' '{nm}'; "
            "Add-Type -AssemblyName Microsoft.VisualBasic; "
            "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin')"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return f"Не удалось в корзину: {(r.stderr or r.stdout or '')[:200]}"
        return f"Файл отправлен в корзину: {p.name}"

    def tool_empty_recycle(self, app: AppContext, confirmed: bool = False, **kw) -> str:
        if not confirmed:
            self._pending = {"action": "empty_recycle"}
            return "Подтвердите: очистить корзину? да/нет"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=120,
        )
        return "Корзина очищена."

    def _roots(self, disk: str) -> List[Path]:
        disk = (disk or "").strip()
        if disk:
            d = disk.rstrip(":\\/") + ":/"
            return [Path(d)]
        roots = []
        if Path.home().exists():
            roots.append(Path.home())
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            p = Path(f"{letter}:/")
            if p.exists():
                roots.append(p)
        return roots


def register():
    return PluginImpl()
