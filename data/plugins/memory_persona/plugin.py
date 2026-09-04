# plugins/memory_persona/plugin.py
"""
Чинит два бага:
  1) Факты пишутся в SQLite, но после рестарта не попадают в промпт
     (поиск LIKE по зашифрованному value + нет «липких» фактов).
  2) Смена персонажа не выкидывает карточку/RAG прошлого —
     «как ты выглядишь» описывает персонажа 1.

Цепляется через plugin_loader. Ядро целиком не подменяем.
"""
from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)

PLUGIN_ID = "memory_persona"
PLUGIN_ENABLED = True

# Совместимость с загрузчиком плагинов ядра: предоставляем PluginImpl
try:
    from core.plugin_api import Plugin as BasePlugin, AppContext
except Exception:
    BasePlugin = object
    AppContext = object


class PluginImpl(BasePlugin):
    id = PLUGIN_ID
    name = "memory_persona"
    version = "1.0.0"

    def on_load(self, app: "AppContext") -> None:
        try:
            # Вызвать старую setup(assistant)
            try:
                Plugin().setup(app)
            except Exception as e:
                logger.error("memory_persona setup failed: %s", e, exc_info=True)
        except Exception:
            pass


STICKY_CATS = {
    "fact", "facts", "profile", "user", "name", "prefer", "prefs",
    "preference", "blocked_url", "note",
}


class Plugin:
    def setup(self, assistant):
        self.assistant = assistant
        _patch_persistent_memory()
        _patch_character_cache()
        _patch_switch_character(assistant)
        _patch_memory_context(assistant)
        logger.info("plugin memory_persona: patches on")


def register():
    return Plugin()


def _patch_persistent_memory():
    try:
        from persistent_memory import PersistentMemory
    except Exception as e:
        logger.warning("memory_persona: no PersistentMemory (%s)", e)
        return
    if getattr(PersistentMemory, "_mp_patched", False):
        return

    orig_search = PersistentMemory.search_memories
    orig_ctx = PersistentMemory.get_context_for_prompt

    def search_memories(self, query, scope=None, limit=10):
        """Не фильтруем SQL по зашифрованному value — только key + расшифровка."""
        import datetime
        import re
        try:
            with self._lock:
                words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) >= 3]
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
                # key только — value зашифрован
                if words:
                    parts = []
                    for word in words:
                        parts.append("LOWER(key) LIKE ?")
                        params.append(f"%{word}%")
                    # не отсекаем SQL-ом: иначе пропадают факты с ключом name/fact
                    # оставляем широкий SELECT, rank после decrypt
                sql += " ORDER BY COALESCE(pinned,0) DESC, COALESCE(importance,0.5) DESC, updated_at DESC"
                sql += " LIMIT ?"
                params.append(max(int(limit or 10) * 8, 40))
                try:
                    self.cursor.execute(sql, params)
                    rows = self.cursor.fetchall()
                except Exception:
                    return orig_search(self, query, scope=scope, limit=limit)

                results = []
                for row in rows:
                    (_id, _scope, category, key, enc, confidence,
                     pinned, importance, expires_at, created_at, updated_at) = row
                    try:
                        value = self._decrypt(enc)
                    except Exception:
                        continue
                    text = (str(key) + " " + str(value)).lower()
                    cat = (category or "").lower()
                    sticky = cat in STICKY_CATS or int(pinned or 0) or float(importance or 0) >= 0.75
                    if words:
                        hit = any(w in text or w in cat for w in words)
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
                    results.append({
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
                    })
                results.sort(key=lambda x: (-int(x.get("sticky") or 0), -int(x.get("pinned") or 0), -x.get("score", 0)))
                return results[:limit]
        except Exception as e:
            logger.error("search_memories patched: %s", e, exc_info=True)
            return orig_search(self, query, scope=scope, limit=limit)

    def get_context_for_prompt(self, query, scope="global", limit=5, max_tokens=500):
        memories = search_memories(self, query, scope=scope, limit=max(int(limit or 5), 8))
        # если поиск по «привет» пустой — всё равно отдать липкие факты
        if not memories:
            memories = search_memories(self, "", scope=scope, limit=limit)
            memories = [m for m in memories if m.get("sticky") or m.get("pinned")][:limit]
        if not memories:
            return orig_ctx(self, query, scope=scope, limit=limit, max_tokens=max_tokens)
        parts = ["\n=== ДОЛГОВРЕМЕННАЯ ПАМЯТЬ (действует и после перезапуска) ===\n"]
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

    PersistentMemory.search_memories = search_memories
    PersistentMemory.get_context_for_prompt = get_context_for_prompt
    PersistentMemory._mp_patched = True
    logger.info("PersistentMemory.search/get_context patched")


def _patch_character_cache():
    try:
        import character_manager as cm
    except Exception:
        return
    if getattr(cm, "_mp_cache_patched", False):
        return

    def invalidate_card_cache():
        cache = getattr(cm, "_card_cache", None)
        if isinstance(cache, dict):
            cache.clear()

    cm.invalidate_card_cache = invalidate_card_cache

    orig = cm.build_character_prompt_block

    def build_character_prompt_block(max_chars: int = 1600):
        block = orig(max_chars=max_chars)
        who = str(getattr(__import__("config"), "ACTIVE_CHARACTER", "") or "").strip()
        lock = (
            f"\n\nЗАМОК ВНЕШНОСТИ. Сейчас ты только «{who}». "
            "Описывай вид ТОЛЬКО из блока «Внешность» этой карточки. "
            "Внешность другого персонажа из RAG, прошлого чата или памяти — запрещена."
        )
        if block and "ЗАМОК ВНЕШНОСТИ" not in block:
            block = block + lock
        return block

    cm.build_character_prompt_block = build_character_prompt_block
    cm._mp_cache_patched = True


def _patch_switch_character(assistant):
    fn = getattr(assistant, "switch_character", None)
    if not callable(fn) or getattr(fn, "_mp_wrapped", False):
        return

    def switch_character(new_name: str):
        name = (new_name or "").strip() or "лисичка"
        try:
            import character_manager as cm
            if hasattr(cm, "invalidate_card_cache"):
                cm.invalidate_card_cache()
            else:
                getattr(cm, "_card_cache", {}).clear()
        except Exception as e:
            logger.debug("cache drop: %s", e)
        result = fn(name)
        # RAG: выкинуть чужие карточки и заново проиндексировать активную
        rag = getattr(assistant, "rag", None)
        if rag is not None:
            try:
                import asyncio
                async def _reindex():
                    prune = getattr(rag, "prune_inactive_personas_async", None)
                    if callable(prune):
                        await prune()
                    auto = getattr(rag, "auto_index_from_config_async", None)
                    if callable(auto):
                        await auto()
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_reindex())
                else:
                    loop.run_until_complete(_reindex())
            except Exception as e:
                logger.warning("switch reindex: %s", e)
        logger.info("switch_character patched → %s", name)
        return result

    switch_character._mp_wrapped = True
    assistant.switch_character = switch_character


def _patch_memory_context(assistant):
    fn = getattr(assistant, "_get_memory_context_async", None)
    if not callable(fn) or getattr(fn, "_mp_wrapped", False):
        return

    async def _get_memory_context_async(query: str) -> str:
        try:
            from memory_scope import prompt_scopes
            scopes = prompt_scopes()
        except Exception:
            scopes = None
        try:
            import config
            limit = int(getattr(config, "MAX_MEMORIES_IN_CONTEXT", 5) or 5)
        except Exception:
            limit = 5
        pm = getattr(assistant, "persistent_memory", None)
        if pm is None:
            return await fn(query)
        try:
            return pm.get_context_for_prompt(
                query=query or "",
                scope=scopes,
                limit=max(limit, 8),
            ) or ""
        except Exception as e:
            logger.error("memory context: %s", e)
            return await fn(query)

    _get_memory_context_async._mp_wrapped = True
    assistant._get_memory_context_async = _get_memory_context_async
