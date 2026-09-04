# -*- coding: utf-8 -*-
"""Долговременная память персонажа (SQLite, без авто-очистки)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class CharacterMemoryStore:
    def __init__(self, character_dir: Path):
        self.character_dir = Path(character_dir)
        self.mem_dir = self.character_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.mem_dir / "memory.db"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL DEFAULT 'fact',
                key TEXT,
                content TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                pinned INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL,
                last_used REAL
            )
            """
        )
        # migrate pinned if old db
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(memories)").fetchall()]
        if "pinned" not in cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN pinned INTEGER DEFAULT 0")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_cat ON memories(category)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_key ON memories(key)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_pin ON memories(pinned)")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def add(
        self,
        content: str,
        category: str = "fact",
        key: Optional[str] = None,
        importance: float = 0.5,
        pinned: bool = False,
    ) -> int:
        content = (content or "").strip()
        if not content:
            return -1
        now = time.time()
        category = (category or "fact").strip() or "fact"
        key = (key or "").strip() or None
        if key:
            row = self._conn.execute(
                "SELECT id FROM memories WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
            if row:
                self._conn.execute(
                    """
                    UPDATE memories
                    SET content=?, category=?, importance=?, pinned=?, updated_at=?, last_used=?
                    WHERE id=?
                    """,
                    (content, category, float(importance), 1 if pinned else 0, now, now, row["id"]),
                )
                self._conn.commit()
                return int(row["id"])
        cur = self._conn.execute(
            """
            INSERT INTO memories(category, key, content, importance, pinned, created_at, updated_at, last_used)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (category, key, content, float(importance), 1 if pinned else 0, now, now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update(
        self,
        mem_id: int,
        content: Optional[str] = None,
        category: Optional[str] = None,
        key: Optional[str] = None,
        importance: Optional[float] = None,
        pinned: Optional[bool] = None,
    ) -> bool:
        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (int(mem_id),)).fetchone()
        if not row:
            return False
        content = row["content"] if content is None else content
        category = row["category"] if category is None else category
        key = row["key"] if key is None else key
        importance = row["importance"] if importance is None else importance
        pinned_v = row["pinned"] if pinned is None else (1 if pinned else 0)
        self._conn.execute(
            """
            UPDATE memories SET content=?, category=?, key=?, importance=?, pinned=?, updated_at=?
            WHERE id=?
            """,
            (content, category, key, float(importance), int(pinned_v), time.time(), int(mem_id)),
        )
        self._conn.commit()
        return True

    def delete(self, mem_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id=?", (int(mem_id),))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self, only_unpinned: bool = False) -> int:
        if only_unpinned:
            cur = self._conn.execute("DELETE FROM memories WHERE IFNULL(pinned,0)=0")
        else:
            cur = self._conn.execute("DELETE FROM memories")
        self._conn.commit()
        return cur.rowcount

    def get(self, mem_id: int) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (int(mem_id),)).fetchone()
        return dict(row) if row else None

    def list_all(self, limit: int = 500) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, category, key, content, importance, pinned, created_at, updated_at, last_used
            FROM memories
            ORDER BY pinned DESC, importance DESC, updated_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_recent(self, limit: int = 20, category: Optional[str] = None) -> List[Dict[str, Any]]:
        if category:
            rows = self._conn.execute(
                """
                SELECT id, category, key, content, importance, pinned, created_at, updated_at
                FROM memories WHERE category=?
                ORDER BY pinned DESC, updated_at DESC LIMIT ?
                """,
                (category, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id, category, key, content, importance, pinned, created_at, updated_at
                FROM memories
                ORDER BY pinned DESC, updated_at DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return self.list_recent(limit=limit)
        like = f"%{q}%"
        rows = self._conn.execute(
            """
            SELECT id, category, key, content, importance, pinned, created_at, updated_at
            FROM memories
            WHERE content LIKE ? OR IFNULL(key,'') LIKE ? OR category LIKE ?
            ORDER BY pinned DESC, importance DESC, updated_at DESC
            LIMIT ?
            """,
            (like, like, like, int(limit)),
        ).fetchall()
        now = time.time()
        for r in rows:
            self._conn.execute("UPDATE memories SET last_used=? WHERE id=?", (now, int(r["id"])))
        self._conn.commit()
        return [dict(r) for r in rows]

    def format_for_prompt(self, items: List[Dict[str, Any]], max_chars: int = 2000) -> str:
        if not items:
            return ""
        lines = ["[долговременная память персонажа]"]
        used = 0
        for it in items:
            cat = it.get("category") or "fact"
            key = it.get("key")
            pin = "📌 " if it.get("pinned") else ""
            body = (it.get("content") or "").strip()
            line = f"- {pin}({cat}" + (f"/{key}" if key else "") + f") {body}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines) if len(lines) > 1 else ""

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()
        return int(row["c"] if row else 0)
