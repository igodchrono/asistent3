# -*- coding: utf-8 -*-
"""Долговременная память (порт asistent2, шифрование опционально)."""
from __future__ import annotations

import base64
import datetime
import logging
import os
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class PersistentMemory:
    def __init__(self, db_path: str = "persistent_memory.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor = None
        self.cipher = None
        self._connect()
        self._init_encryption()

    def _connect(self) -> None:
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.cursor = self.conn.cursor()
        self._init_db()

    def _init_db(self) -> None:
        assert self.cursor and self.conn
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(scope, category, key)
            )
            """
        )
        self.conn.commit()
        cols = {r[1] for r in self.cursor.execute("PRAGMA table_info(memories)").fetchall()}
        for col, sql in (
            ("pinned", "ALTER TABLE memories ADD COLUMN pinned INTEGER DEFAULT 0"),
            ("importance", "ALTER TABLE memories ADD COLUMN importance REAL DEFAULT 0.5"),
            ("expires_at", "ALTER TABLE memories ADD COLUMN expires_at TEXT"),
        ):
            if col not in cols:
                try:
                    self.cursor.execute(sql)
                except Exception:
                    pass
        self.conn.commit()

    def _init_encryption(self) -> None:
        try:
            from cryptography.fernet import Fernet

            key_file = os.path.join(os.path.dirname(self.db_path) or ".", "secret.key")
            if os.path.exists(key_file):
                with open(key_file, "rb") as f:
                    self.cipher = Fernet(f.read())
            else:
                key = Fernet.generate_key()
                with open(key_file, "wb") as f:
                    f.write(key)
                self.cipher = Fernet(key)
        except Exception as e:
            logger.warning("PersistentMemory: без шифрования (%s)", e)
            self.cipher = None

    def _encrypt(self, text: str) -> str:
        if not text:
            return ""
        if self.cipher is None:
            return text
        return base64.b64encode(self.cipher.encrypt(text.encode())).decode()

    def _decrypt(self, encrypted: str) -> str:
        if not encrypted:
            return ""
        if self.cipher is None:
            return encrypted
        try:
            return self.cipher.decrypt(base64.b64decode(encrypted)).decode()
        except Exception:
            return encrypted  # возможно старый plaintext

    def add_memory(
        self,
        scope: str,
        category: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        importance: float = 0.5,
        pinned: bool = False,
        expires_at: Optional[str] = None,
    ) -> None:
        try:
            with self._lock:
                assert self.cursor and self.conn
                enc = self._encrypt(value)
                now = datetime.datetime.now().isoformat()
                self.cursor.execute(
                    """
                    INSERT INTO memories
                    (scope, category, key, value, confidence, created_at, updated_at,
                     pinned, importance, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scope, category, key) DO UPDATE SET
                        value=excluded.value,
                        confidence=excluded.confidence,
                        updated_at=excluded.updated_at,
                        importance=MAX(memories.importance, excluded.importance),
                        pinned=MAX(memories.pinned, excluded.pinned),
                        expires_at=COALESCE(excluded.expires_at, memories.expires_at)
                    """,
                    (
                        scope,
                        category,
                        key,
                        enc,
                        confidence,
                        now,
                        now,
                        1 if pinned else 0,
                        float(importance),
                        expires_at,
                    ),
                )
                self.conn.commit()
        except Exception as e:
            logger.error("add_memory: %s", e)
            try:
                self.conn and self.conn.rollback()
            except Exception:
                pass

    def get_memory(self, scope: str, category: str, key: str) -> Optional[Dict[str, Any]]:
        try:
            with self._lock:
                assert self.cursor
                self.cursor.execute(
                    "SELECT value, confidence FROM memories WHERE scope=? AND category=? AND key=?",
                    (scope, category, key),
                )
                row = self.cursor.fetchone()
                if row:
                    return {"value": self._decrypt(row[0]), "confidence": row[1]}
                return None
        except Exception as e:
            logger.error("get_memory: %s", e)
            return None

    def search_memories(
        self, query: str, scope: Optional[Union[str, list]] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        try:
            with self._lock:
                assert self.cursor
                words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) >= 2]
                now_iso = datetime.datetime.now().isoformat()
                sql = """
                    SELECT id, scope, category, key, value, confidence,
                           COALESCE(pinned, 0), COALESCE(importance, 0.5),
                           expires_at, created_at, updated_at
                    FROM memories
                    WHERE COALESCE(confidence, 0) > 0.05
                      AND (expires_at IS NULL OR expires_at >= ?)
                """
                params: List[Any] = [now_iso]
                if scope:
                    if isinstance(scope, (list, tuple, set)):
                        scopes = [str(s) for s in scope if s]
                        if scopes:
                            sql += " AND scope IN ({})".format(",".join("?" * len(scopes)))
                            params.extend(scopes)
                    else:
                        sql += " AND scope = ?"
                        params.append(scope)
                sql += " ORDER BY COALESCE(pinned,0) DESC, COALESCE(importance,0.5) DESC, updated_at DESC"
                sql += " LIMIT ?"
                params.append(max(limit * 8, 40))
                self.cursor.execute(sql, params)
                rows = self.cursor.fetchall()
                results = []
                sticky_cats = {
                    "fact",
                    "facts",
                    "profile",
                    "user",
                    "name",
                    "prefer",
                    "prefs",
                    "preference",
                    "note",
                }
                for row in rows:
                    (
                        _id,
                        _scope,
                        category,
                        key,
                        enc,
                        confidence,
                        pinned,
                        importance,
                        expires_at,
                        created_at,
                        updated_at,
                    ) = row
                    try:
                        value = self._decrypt(enc)
                    except Exception:
                        continue
                    text = (str(key) + " " + str(value)).lower()
                    cat = (category or "").lower()
                    sticky = cat in sticky_cats or int(pinned or 0) or float(importance or 0) >= 0.75
                    if words:
                        hit = any(w in text or w in cat or w in str(key).lower() for w in words)
                        if not hit and not sticky:
                            continue
                        tf = sum(text.count(w) for w in words) / (len(text.split()) + 1)
                    else:
                        tf = 0.15 if sticky else 0.05
                    pin_boost = 0.35 if int(pinned or 0) else 0.0
                    if sticky:
                        pin_boost += 0.25
                    imp = float(importance or 0.5)
                    conf = float(confidence or 0)
                    results.append(
                        {
                            "id": _id,
                            "scope": _scope,
                            "category": category,
                            "key": key,
                            "value": value,
                            "confidence": conf,
                            "pinned": bool(int(pinned or 0)),
                            "importance": imp,
                            "score": tf * 0.45 + imp * 0.25 + conf * 0.15 + pin_boost,
                            "created_at": created_at,
                            "updated_at": updated_at,
                            "sticky": sticky,
                        }
                    )
                results.sort(
                    key=lambda x: (
                        -int(x.get("sticky") or 0),
                        -int(x.get("pinned") or 0),
                        -x.get("score", 0),
                    )
                )
                return results[:limit]
        except Exception as e:
            logger.error("search_memories: %s", e)
            return []

    def get_context_for_prompt(
        self, query: str, scope: Any = "global", limit: int = 5, max_tokens: int = 500
    ) -> str:
        memories = self.search_memories(query, scope=scope, limit=max(int(limit or 5), 8))
        if not memories:
            memories = [
                m
                for m in self.search_memories("", scope=scope, limit=limit)
                if m.get("sticky") or m.get("pinned")
            ][:limit]
        if not memories:
            return ""
        parts = ["\n=== ДОЛГОВРЕМЕННАЯ ПАМЯТЬ ===\n"]
        seen = set()
        for mem in memories:
            mark = (mem.get("scope"), mem.get("category"), mem.get("key"))
            if mark in seen:
                continue
            seen.add(mark)
            pin = "📌 " if mem.get("pinned") or mem.get("sticky") else ""
            sc = mem.get("scope") or ""
            tag = f"{sc}/{mem['category']}" if sc else mem["category"]
            parts.append(f"{pin}[{tag}] {mem['key']}: {mem['value']}")
        text = "\n".join(parts)
        cap = int(max_tokens or 500) * 4
        if len(text) > cap:
            text = text[:cap] + "\n… (память обрезана)"
        return text

    def close(self) -> None:
        try:
            with self._lock:
                if self.conn:
                    self.conn.close()
                    self.conn = None
                    self.cursor = None
        except Exception as e:
            logger.warning("PersistentMemory.close: %s", e)
