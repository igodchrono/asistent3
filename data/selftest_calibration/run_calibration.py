# -*- coding: utf-8 -*-
"""
Калибровочный selftest asistent3.
Папка selftest_calibration/ — можно удалить целиком.

Запуск из data/:
  ..\\python\\python.exe -u selftest_calibration\\run_calibration.py
  ..\\python\\python.exe -u selftest_calibration\\run_calibration.py --llm --browser
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# data/ as cwd
DATA = Path(__file__).resolve().parent.parent
if str(DATA) not in sys.path:
    sys.path.insert(0, str(DATA))
os.chdir(DATA)

LOG = DATA / "selftest_calibration_run.log"


class T:
    def __init__(self):
        self.ok = self.fail = self.warn = self.skip = 0
        self.lines = []

    def _w(self, s: str):
        print(s, flush=True)
        self.lines.append(s)

    def section(self, title: str):
        self._w("")
        self._w("=" * 60)
        self._w(title)
        self._w("=" * 60)

    def pass_(self, name: str, detail: str = ""):
        self.ok += 1
        self._w(f"  OK   [{name}] {detail}"[:200])

    def fail_(self, name: str, detail: str = ""):
        self.fail += 1
        self._w(f"  FAIL [{name}] {detail}"[:300])

    def warn_(self, name: str, detail: str = ""):
        self.warn += 1
        self._w(f"  WARN [{name}] {detail}"[:200])

    def skip_(self, name: str, detail: str = ""):
        self.skip += 1
        self._w(f"  SKIP [{name}] {detail}"[:200])

    def save(self):
        LOG.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def boot_app(t: T):
    """Минимальный boot без GUI-окна если возможно."""
    import config
    from settings_manager import apply_to_config
    from core.plugin_api import AppContext
    from core.plugin_loader import PluginLoader
    from core.llm_client import LLMClient

    apply_to_config(config)
    # Qt app required by many plugins
    from PyQt5.QtCore import Qt, QCoreApplication
    try:
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    except Exception:
        pass
    from PyQt5.QtWidgets import QApplication
    import sys as _sys
    if not QApplication.instance():
        app_qt = QApplication(_sys.argv)
    else:
        app_qt = QApplication.instance()

    ctx = AppContext(config)
    try:
        ctx.llm = LLMClient.from_config(config)
    except Exception as e:
        t.warn_("llm_init", str(e))
        ctx.llm = None
    loader = PluginLoader(ctx)
    try:
        loader.load_all()
    except Exception:
        # older API
        if hasattr(loader, "load"):
            loader.load()
        elif hasattr(loader, "discover_and_load"):
            loader.discover_and_load()
    t.pass_("boot", f"plugins={list(ctx.plugins.keys())}")
    return ctx, app_qt


def test_plugins_loaded(ctx, t: T):
    t.section("0. Плагины загружены")
    need = [
        "browser_search", "memory", "emotion", "avatar",
        "pc_control", "deep_think", "screen_vision", "screen_react",
    ]
    optional = ["companion", "notes", "reminders", "voice", "rag", "browser_embed"]
    for pid in need:
        if pid in ctx.plugins:
            t.pass_(f"plugin:{pid}", "loaded")
        else:
            t.fail_(f"plugin:{pid}", "не найден")
    for pid in optional:
        if pid in ctx.plugins:
            t.pass_(f"plugin:{pid}", "loaded (opt)")
        else:
            t.skip_(f"plugin:{pid}", "нет — ок")
    emb = ctx.plugins.get("browser_embed")
    if emb:
        en = ctx.get_plugin_setting("browser_embed", "enabled", False)
        if en:
            t.warn_("browser_embed", "ВКЛ — для калибровки лучше выключить")
        else:
            t.pass_("browser_embed", "OFF — хорошо для калибровки")


def test_browser(ctx, t: T, do_browser: bool):
    t.section("1. browser_search")
    pl = ctx.plugins.get("browser_search")
    if not pl:
        t.fail_("browser", "плагин нет")
        return
    # normalize
    if hasattr(pl, "_normalize_query"):
        n = pl._normalize_query("найди пожалуйста картинки рыжих котов в интернете")
        if "рыж" in n.lower() or "кот" in n.lower():
            t.pass_("normalize", repr(n)[:80])
        else:
            t.warn_("normalize", repr(n)[:80])
    else:
        t.skip_("normalize", "нет метода")
    # split
    if hasattr(pl, "_split_user_queries"):
        qs = pl._split_user_queries("найди котов и ещё найди лисичек")
        if len(qs) >= 2:
            t.pass_("split", str(qs)[:100])
        else:
            t.warn_("split", str(qs))
    # embed not forced
    if hasattr(pl, "_use_embed"):
        use = pl._use_embed(ctx)
        if use:
            t.warn_("use_embed", "True — откроет встроенный")
        else:
            t.pass_("use_embed", "False — системный браузер")
    if not do_browser:
        t.skip_("open_real", "запуск без --browser")
        return
    try:
        r = pl.tool_web_search(ctx, query="рыжие коты test calibration", mode="images")
        if "SEARCH_OK" in str(r).upper() or "открыт" in str(r).lower() or "OK" in str(r).upper():
            t.pass_("open_search", str(r)[:100])
        else:
            t.warn_("open_search", str(r)[:120])
        # must not be EMBED if embed off
        if "EMBED" in str(r).upper() and ctx.get_plugin_setting("browser_embed", "enabled", False) is False:
            t.warn_("embed_leak", str(r)[:80])
    except Exception as e:
        t.fail_("open_search", str(e))


def test_memory(ctx, t: T):
    t.section("2. memory")
    pl = ctx.plugins.get("memory")
    if not pl:
        t.fail_("memory", "нет плагина")
        return
    token = f"calib_token_{int(time.time()) % 100000}"
    try:
        if hasattr(pl, "tool_add"):
            r = pl.tool_add(ctx, text=f"профиль: {token}")
            t.pass_("memory_add", str(r)[:100])
        else:
            t.fail_("memory_add", "нет tool_add")
            return
        if hasattr(pl, "tool_list"):
            r = pl.tool_list(ctx)
            if token in str(r):
                t.pass_("memory_list", "token found")
            else:
                t.warn_("memory_list", str(r)[:120])
        # isolation path exists
        store = getattr(pl, "store", None)
        if store is not None:
            t.pass_("memory_store", type(store).__name__)
        else:
            t.warn_("memory_store", "store is None")
    except Exception as e:
        t.fail_("memory", f"{e}\n{traceback.format_exc()[:200]}")


def test_emotion_anim(ctx, t: T):
    t.section("3. emotion / ANIM strip")
    # strip helper from chat engine
    try:
        from core.chat_engine import ChatEngine
        if hasattr(ChatEngine, "_strip_anim_for_chat"):
            s = ChatEngine._strip_anim_for_chat("Привет [ANIM:playful] мир")
            if "[ANIM" not in s and "Привет" in s and "мир" in s:
                t.pass_("strip_anim", repr(s))
            else:
                t.fail_("strip_anim", repr(s))
        else:
            t.warn_("strip_anim", "метода нет в ChatEngine")
        if hasattr(ChatEngine, "_strip_anim_tags_only"):
            s = ChatEngine._strip_anim_tags_only("а [ANIM:sad] б")
            if "[ANIM" not in s:
                t.pass_("strip_tags_only", repr(s))
            else:
                t.fail_("strip_tags_only", repr(s))
    except Exception as e:
        t.fail_("chat_engine_strip", str(e))
    em = ctx.plugins.get("emotion")
    if em:
        t.pass_("emotion_plugin", "loaded")
    av = ctx.plugins.get("avatar")
    if av:
        t.pass_("avatar_plugin", "loaded")


def test_pc(ctx, t: T, safe: bool):
    t.section("4. pc_control")
    pl = ctx.plugins.get("pc_control")
    if not pl:
        t.fail_("pc", "нет")
        return
    # pronouns must not open as file via on_user_message
    if hasattr(pl, "on_user_message"):
        from core.plugin_api import HookResult
        hr = pl.on_user_message("открой её", ctx)
        if hr is None:
            t.pass_("pc_skip_pronoun", "None — не файл")
        elif isinstance(hr, HookResult) and hr.handled and "Не найдено" in str(hr.reply):
            t.fail_("pc_skip_pronoun", "всё ещё ловит «её»")
        else:
            t.warn_("pc_skip_pronoun", str(hr)[:100])
    if not safe:
        t.skip_("pc_open", "без реального open (safe)")
        return
    try:
        r = pl.tool_open(ctx, target="notepad")
        t.pass_("pc_open_notepad", str(r)[:80])
    except Exception as e:
        t.warn_("pc_open_notepad", str(e))


def test_screen(ctx, t: T):
    t.section("5. screen")
    for pid in ("screen_vision", "screen_react"):
        if pid in ctx.plugins:
            t.pass_(pid, "loaded")
        else:
            t.skip_(pid, "нет")
    # react infer if exists
    pl = ctx.plugins.get("screen_react")
    if pl and hasattr(pl, "_infer"):
        try:
            emo, anim, conf = pl._infer("code visual studio", None, nsfw_allowed=False)
            t.pass_("screen_infer", f"{emo}/{anim} conf={conf}")
        except TypeError:
            try:
                r = pl._infer("chrome google search")
                t.pass_("screen_infer", str(r)[:80])
            except Exception as e:
                t.warn_("screen_infer", str(e))
        except Exception as e:
            t.warn_("screen_infer", str(e))


def test_companion(ctx, t: T):
    t.section("6. companion")
    pl = ctx.plugins.get("companion")
    if not pl:
        t.skip_("companion", "нет")
        return
    if hasattr(pl, "_tick_time"):
        pl._tick_time(ctx)
        if ctx.state.get("local_time"):
            t.pass_("time", f"{ctx.state.get('local_date')} {ctx.state.get('local_time')}")
        else:
            t.fail_("time", "нет local_time")
    if hasattr(pl, "_system_block"):
        block = pl._system_block(ctx)
        if "COMPANION" in block or "Сейчас" in block:
            t.pass_("system_block", f"len={len(block)}")
        else:
            t.warn_("system_block", block[:100])


def test_deep_think(ctx, t: T):
    t.section("7. deep_think")
    pl = ctx.plugins.get("deep_think")
    if not pl:
        t.skip_("deep_think", "нет")
        return
    t.pass_("deep_think", "loaded")
    if hasattr(pl, "on_user_message"):
        hr = pl.on_user_message("объясни подробно что такое asyncio", ctx)
        t.pass_("deep_phrase", str(hr)[:100] if hr else "pass-through None")


def test_llm(ctx, t: T, do_llm: bool):
    t.section("8. LLM (optional)")
    if not do_llm:
        t.skip_("llm", "без --llm")
        return
    llm = getattr(ctx, "llm", None)
    if not llm:
        t.fail_("llm", "нет клиента")
        return
    try:
        import asyncio

        async def ping():
            # try models endpoint style
            if hasattr(llm, "base_url"):
                return str(getattr(llm, "base_url", ""))
            return "ok"

        base = asyncio.get_event_loop().run_until_complete(ping()) if False else getattr(llm, "base_url", "llm")
        t.pass_("llm_client", str(base)[:80])
        # short chat if possible
        if hasattr(llm, "chat_once"):
            async def one():
                return await llm.chat_once(
                    [{"role": "user", "content": "Ответь одним словом: два плюс два"}],
                    temperature=0.1,
                    max_tokens=16,
                )
            try:
                loop = asyncio.new_event_loop()
                ans = loop.run_until_complete(one())
                loop.close()
                t.pass_("llm_short", str(ans)[:80])
            except Exception as e:
                t.warn_("llm_short", str(e)[:120])
    except Exception as e:
        t.warn_("llm", str(e))


def main():
    ap = argparse.ArgumentParser(description="Calibration selftest (удаляемая папка)")
    ap.add_argument("--llm", action="store_true", help="пинг LLM / короткий ответ")
    ap.add_argument("--browser", action="store_true", help="реальный open поиска")
    ap.add_argument("--pc", action="store_true", help="реальный open notepad")
    args = ap.parse_args()

    t = T()
    t._w(f"selftest_calibration {datetime.now().isoformat(timespec='seconds')}")
    t._w(f"cwd={Path.cwd()}")
    t._w(f"flags llm={args.llm} browser={args.browser} pc={args.pc}")

    try:
        ctx, app_qt = boot_app(t)
    except Exception as e:
        t.fail_("boot", f"{e}\n{traceback.format_exc()}")
        t.save()
        print(f"\nLog: {LOG}")
        sys.exit(2)

    test_plugins_loaded(ctx, t)
    test_browser(ctx, t, args.browser)
    test_memory(ctx, t)
    test_emotion_anim(ctx, t)
    test_pc(ctx, t, args.pc)
    test_screen(ctx, t)
    test_companion(ctx, t)
    test_deep_think(ctx, t)
    test_llm(ctx, t, args.llm)

    t.section("ИТОГО")
    t._w(f"OK={t.ok} FAIL={t.fail} WARN={t.warn} SKIP={t.skip}")
    t.save()
    t._w(f"лог: {LOG}")
    t._w("Папку selftest_calibration/ можно удалить целиком.")
    code = 1 if t.fail else 0
    sys.exit(code)


if __name__ == "__main__":
    main()
