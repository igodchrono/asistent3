# -*- coding: utf-8 -*-
"""Простой keyword-RAG по файлам персонажа (md/txt) без FAISS."""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.plugin_api import AppContext, Plugin, SettingField


class PluginImpl(Plugin):
    id = "rag"
    name = "RAG (файлы персонажа)"
    version = "1.0.0"
    description = "Keyword-поиск по .md/.txt персонажа и вставка в промпт"
    settings_tab = "own"
    settings_tab_title = "RAG"
    settings_schema = [
        SettingField("enabled", "Включить", "bool", True),
        SettingField("auto_index_on_load", "Индексировать при старте", "bool", True),
        SettingField("inject_prompt", "Вставлять находки в промпт", "bool", True),
        SettingField("max_chunks", "Макс. чанков в промпте", "int", 4, min_value=1, max_value=20),
        SettingField("min_query_len", "Мин. длина запроса для поиска", "int", 4, min_value=1, max_value=50),
    ]

    def __init__(self):
        self.app: Optional[AppContext] = None
        self.db_path: Optional[Path] = None
        self._lock = threading.Lock()

    def on_load(self, app: AppContext) -> None:
        self.app = app
        self._setup_db(app)
        if app.get_plugin_setting(self.id, "auto_index_on_load", True):
            n = self.reindex(app)
            print(f"📚 rag: indexed chunks={n}", flush=True)
        else:
            print("📚 rag: loaded", flush=True)

    def on_character_changed(self, character_id, previous_id, app):
        self.app = app
        self._setup_db(app)
        if app.get_plugin_setting(self.id, "auto_index_on_load", True):
            self.reindex(app)

    def on_before_llm(self, messages: List[Dict[str, Any]], app: AppContext) -> List[Dict[str, Any]]:
        if not app.get_plugin_setting(self.id, "enabled", True):
            return messages
        if not app.get_plugin_setting(self.id, "inject_prompt", True) or not messages:
            return messages
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                query = m["content"]
                break
        min_len = int(app.get_plugin_setting(self.id, "min_query_len", 4) or 4)
        if len(query.strip()) < min_len:
            return messages
        limit = int(app.get_plugin_setting(self.id, "max_chunks", 4) or 4)
        hits = self.search(app, query, limit=limit)
        if not hits:
            return messages
        block = "\n=== КОНТЕКСТ ИЗ ФАЙЛОВ ПЕРСОНАЖА ===\n" + "\n---\n".join(hits)
        if messages[0].get("role") == "system":
            cur = str(messages[0].get("content") or "")
            if "КОНТЕКСТ ИЗ ФАЙЛОВ" not in cur:
                messages[0]["content"] = cur + "\n" + block
        return messages

    def index_text(self, app: AppContext, text: str, source: str = "manual") -> None:
        if not text.strip():
            return
        self._setup_db(app)
        assert self.db_path
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "INSERT INTO chunks (source, text) VALUES (?, ?)",
                (source, text.strip()[:2000]),
            )
            conn.commit()
            conn.close()

    def reindex(self, app: AppContext) -> int:
        self._setup_db(app)
        assert self.db_path
        cdir = app.get_character_dir()
        files = []
        for pattern in ("*.md", "*.txt"):
            files.extend(cdir.glob(pattern))
            files.extend((cdir / "docs").glob(pattern) if (cdir / "docs").is_dir() else [])
        chunks: List[tuple] = []
        for f in files:
            try:
                raw = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for part in self._split(raw):
                chunks.append((str(f.name), part))
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("DELETE FROM chunks")
            conn.executemany("INSERT INTO chunks (source, text) VALUES (?, ?)", chunks)
            conn.commit()
            conn.close()
        return len(chunks)

    def search(self, app: AppContext, query: str, limit: int = 4) -> List[str]:
        self._setup_db(app)
        words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) >= 3]
        if not words or not self.db_path:
            return []
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            rows = conn.execute("SELECT source, text FROM chunks").fetchall()
            conn.close()
        scored = []
        for source, text in rows:
            low = text.lower()
            score = sum(low.count(w) for w in words)
            if score > 0:
                scored.append((score, f"[{source}] {text[:400]}"))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:limit]]

    def _setup_db(self, app: AppContext) -> None:
        try:
            cdir = app.get_character_dir()
            path = cdir / "memory" / "rag_keyword.db"
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            path = Path(getattr(app.config, "DATA_DIR", Path("."))) / "rag_keyword.db"
        self.db_path = path
        conn = sqlite3.connect(str(path))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                text TEXT
            )"""
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _split(text: str, size: int = 400, overlap: int = 40) -> List[str]:
        text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
        if not text:
            return []
        if len(text) <= size:
            return [text]
        out = []
        i = 0
        while i < len(text):
            out.append(text[i : i + size])
            i += max(1, size - overlap)
        return out


def register() -> PluginImpl:
    return PluginImpl()


Plugin = PluginImpl
