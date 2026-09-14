# -*- coding: utf-8 -*-
"""Единственное хранилище памяти персонажа: memory/memory.db

Старые файлы (persistent.db, persistent_memory.db, chat.db) не используются
и не создаются. Если лежат рядом — игнорируются.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_STOP = {
    "это", "как", "что", "кто", "где", "когда", "меня", "тебя", "тебе",
    "привет", "пока", "ну", "да", "нет", "ок", "окей", "просто", "очень",
    "the", "and", "you", "what", "how", "hey", "hi", "please",
}


class CharacterMemoryStore:
    def __init__(self, character_dir: Path, character_id: str = ""):
        self.character_id = (character_id or Path(character_dir).name).strip() or "default"
        self.character_dir = Path(character_dir)
        self.character_dir.mkdir(parents=True, exist_ok=True)
        self.mem_dir = self.character_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.mem_dir / "memory.db"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
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
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(memories)").fetchall()]
        if "pinned" not in cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN pinned INTEGER DEFAULT 0")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_cat ON memories(category)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_key ON memories(key)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_pin ON memories(pinned)")
        self._conn.commit()
        self._init_dialog_schema()

    def close(self) -> None:
        try:
            self._conn.commit()
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

    def list_sticky(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, category, key, content, importance, pinned, created_at, updated_at
            FROM memories
            WHERE IFNULL(pinned,0)=1
               OR category IN ('longterm','fact','user','preference','profile','blocked_url')
               OR IFNULL(importance,0) >= 0.75
            ORDER BY pinned DESC, importance DESC, updated_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return self.list_recent(limit=limit)
        tokens = [
            t for t in re.findall(r"[A-Za-zА-Яа-яЁё0-9_\-]{3,}", q.lower())
            if t not in _STOP
        ]
        clauses = ["IFNULL(pinned,0)=1"]
        params: List[Any] = []
        if tokens:
            for tok in tokens[:8]:
                clauses.append(
                    "(LOWER(content) LIKE ? OR LOWER(IFNULL(key,'')) LIKE ? OR LOWER(category) LIKE ?)"
                )
                like = f"%{tok}%"
                params.extend([like, like, like])
        else:
            clauses.append("(LOWER(content) LIKE ? OR LOWER(IFNULL(key,'')) LIKE ?)")
            like = f"%{q.lower()}%"
            params.extend([like, like])
        sql = f"""
            SELECT id, category, key, content, importance, pinned, created_at, updated_at
            FROM memories
            WHERE {" OR ".join(clauses)}
            ORDER BY pinned DESC, importance DESC, updated_at DESC
            LIMIT ?
        """
        params.append(max(int(limit) * 3, 16))
        rows = self._conn.execute(sql, params).fetchall()
        now = time.time()
        out: List[Dict[str, Any]] = []
        seen = set()
        for r in rows:
            rid = int(r["id"])
            if rid in seen:
                continue
            seen.add(rid)
            try:
                self._conn.execute("UPDATE memories SET last_used=? WHERE id=?", (now, rid))
            except Exception:
                pass
            out.append(dict(r))
            if len(out) >= int(limit):
                break
        self._conn.commit()
        return out

    def recall_for_prompt(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        sticky = self.list_sticky(limit=max(int(limit), 10))
        found = self.search(query, limit=limit) if (query or "").strip() else []
        merged: List[Dict[str, Any]] = []
        seen = set()
        for it in sticky + found:
            rid = it.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            merged.append(it)
            if len(merged) >= int(limit):
                break
        if not merged:
            merged = self.list_recent(limit=limit)
        return merged

    def format_for_prompt(self, items: List[Dict[str, Any]], max_chars: int = 2000) -> str:
        if not items:
            return ""
        who = self.character_id
        lines = [
            f"[долговременная память персонажа «{who}» — только этого персонажа, действует после перезапуска]",
            "Это уже известные факты. Используй их, даже если в текущей реплике их нет. Не путай с памятью другого персонажа.",
        ]
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
        return "\n".join(lines) if len(lines) > 2 else ""

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()
        return int(row["c"] if row else 0)

    # ---- диалог / дневник (тот же sqlite, этот персонаж) ----

    def _init_dialog_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL UNIQUE,
                text TEXT NOT NULL,
                from_id INTEGER,
                to_id INTEGER,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_time ON messages(created_at)")
        self._conn.commit()

    @staticmethod
    def day_of(ts: Optional[float] = None) -> str:
        from datetime import datetime
        return datetime.fromtimestamp(float(ts if ts is not None else time.time())).strftime("%Y-%m-%d")

    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row and row["value"] is not None else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self._conn.commit()

    def append_message(self, role: str, content: str) -> int:
        role = "assistant" if str(role) == "assistant" else "user"
        text = (content or "").strip()
        if not text:
            return -1
        if len(text) > 8000:
            text = text[:8000] + "…"
        cur = self._conn.execute(
            "INSERT INTO messages(role, content, created_at) VALUES(?,?,?)",
            (role, text, time.time()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def message_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()
        return int(row["c"] if row else 0)

    def last_message_id(self) -> int:
        row = self._conn.execute("SELECT MAX(id) AS m FROM messages").fetchone()
        return int(row["m"] or 0)

    def recent_messages(self, limit: int = 16) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, role, content, created_at FROM messages
            ORDER BY id DESC LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        out = [dict(r) for r in rows]
        out.reverse()
        return out

    def messages_between(self, after_id: int, before_id: int, limit: int = 80) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, role, content, created_at FROM messages
            WHERE id > ? AND id < ?
            ORDER BY id ASC LIMIT ?
            """,
            (int(after_id), int(before_id), max(1, int(limit))),
        ).fetchall()
        return [dict(r) for r in rows]

    def pending_summary_groups(self, tail: int = 16, min_today: int = 6) -> List[Dict[str, Any]]:
        """Сообщения старше хвоста, ещё не вошедшие в дневник, группами по дню."""
        tail_rows = self.recent_messages(limit=tail)
        if not tail_rows:
            return []
        covered = int(self.get_meta("summarized_upto") or 0)
        tail_min = int(tail_rows[0]["id"])
        if tail_min <= covered + 1:
            return []
        old = self.messages_between(covered, tail_min, limit=120)
        if not old:
            return []
        today = self.day_of()
        groups: Dict[str, List[Dict[str, Any]]] = {}
        order: List[str] = []
        for m in old:
            day = self.day_of(m.get("created_at"))
            if day not in groups:
                groups[day] = []
                order.append(day)
            groups[day].append(m)
        out: List[Dict[str, Any]] = []
        for day in order:
            msgs = groups[day]
            if day < today or len(msgs) >= int(min_today):
                out.append({"day": day, "messages": msgs})
        return out

    def get_summary(self, day: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM summaries WHERE day=?", (day,)).fetchone()
        return dict(row) if row else None

    def upsert_summary(self, day: str, text: str, from_id: int, to_id: int) -> None:
        text = (text or "").strip()
        if not text:
            return
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO summaries(day, text, from_id, to_id, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET
                text=excluded.text,
                from_id=excluded.from_id,
                to_id=excluded.to_id,
                updated_at=excluded.updated_at
            """,
            (day, text[:4000], int(from_id), int(to_id), now, now),
        )
        prev = int(self.get_meta("summarized_upto") or 0)
        if int(to_id) > prev:
            self.set_meta("summarized_upto", str(int(to_id)))
        else:
            self._conn.commit()

    def recent_summaries(self, limit: int = 7) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT day, text, from_id, to_id, updated_at FROM summaries
            ORDER BY day DESC LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        out = [dict(r) for r in rows]
        out.reverse()
        return out

    def format_diary(self, limit_days: int = 7, max_chars: int = 2200) -> str:
        items = self.recent_summaries(limit=limit_days)
        if not items:
            return ""
        lines = [
            "[ДНЕВНИК ДИАЛОГА этого персонажа — помни и ссылайся, если спрашивают про вчера/раньше]",
            "Не говори «я не помню», если день есть ниже.",
        ]
        used = 0
        for it in items:
            block = f"{it.get('day')}: {(it.get('text') or '').strip()}"
            if used + len(block) > max_chars:
                break
            lines.append(block)
            used += len(block)
        return "\n".join(lines) if len(lines) > 2 else ""

# alias for plugins
MemoryStore = CharacterMemoryStore
