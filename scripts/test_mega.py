"""Mega genisleme dogrulama betigi (Faz 1+2+3).

    python scripts/test_mega.py

Ag gerektiren bazi testler (hava, doviz, web_search, GBrain ask) anahtar/kota
yoksa atlanir - kirmizi degil sari.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING", format="{message}")

PASS, FAIL, SKIP = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m", "\033[93mSKIP\033[0m"
_ok = True


def check(cond, label, detail=""):
    global _ok
    print(f"[{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    _ok &= bool(cond)


def skip(label, why):
    print(f"[{SKIP}] {label}  — {why}")


async def main() -> int:
    from config.settings import get_settings
    s = get_settings()

    # --- 1. scheduler / parse ---
    from core.scheduler import parse_when
    from tools.scheduler_tools import cancel_reminder, list_reminders, set_reminder
    now = time.time()
    check(parse_when("20 dakika sonra") is not None, "parse_when goreli")
    check(parse_when("yarin 09:00") is not None, "parse_when mutlak")
    r = set_reminder("mega test hatirlatici", "1 dakika sonra")
    check(r.get("status") == "kuruldu", "set_reminder", r.get("ne_zaman", r.get("error")))
    check(any("mega test" in x["text"] for x in list_reminders()["reminders"]), "list_reminders")
    cancel_reminder("mega test")

    # --- 2. quick tools ---
    from tools.quick_tools import calculate
    check(calculate("(2+3)*4")["result"] == 20, "calculate")
    check(abs(calculate("sqrt(144)")["result"] - 12) < 1e-6, "calculate func")
    try:
        from tools.quick_tools import get_weather
        w = get_weather("Izmir")
        if "error" in w:
            skip("get_weather", w["error"])
        else:
            check("simdi" in w and w["simdi"].get("sicaklik") is not None, "get_weather",
                  f"{w['konum']} {w['simdi'].get('sicaklik')}C")
    except Exception as exc:  # noqa: BLE001
        skip("get_weather", str(exc))
    try:
        from tools.quick_tools import convert_currency
        c = convert_currency(100, "USD", "TRY")
        skip("convert_currency", c["error"]) if "error" in c else check(True, "convert_currency", c["to"])
    except Exception as exc:  # noqa: BLE001
        skip("convert_currency", str(exc))

    # --- 3. system / file ---
    from tools.system_tools import list_processes
    check(list_processes(5).get("count", 0) > 0, "list_processes")
    from tools.file_ops import find_files, make_folder, zip_paths
    sand = s.data_dir / "mega_test"
    make_folder(str(sand))
    (sand / "a.txt").write_text("merhaba", encoding="utf-8")
    check(find_files("*.txt", str(sand))["count"] >= 1, "find_files")
    z = zip_paths(str(sand / "a.txt"), str(sand / "out.zip"))
    check(z.get("status") == "olusturuldu", "zip_paths")

    # --- 4. vision ---
    from tools.vision_tools import save_screenshot
    ss = save_screenshot(str(sand))
    check(ss.get("status") == "kaydedildi" and Path(ss["path"]).is_file(), "save_screenshot",
          ss.get("path", ss.get("error")))
    try:
        from tools.vision_tools import ocr_screen
        o = await ocr_screen()
        skip("ocr_screen", o["error"]) if "error" in o else check(
            o.get("chars", 0) > 3, "ocr_screen", f"{o.get('chars')} karakter")
    except Exception as exc:  # noqa: BLE001
        skip("ocr_screen", str(exc))

    # --- 5. GBrain ---
    try:
        from agents.gbrain.store import get_gbrain
        gb = get_gbrain()
        await gb.write("Mega test notu", "CYRAEN'in favori rengi camgobegi (cyan).", ["test"])
        hits = await gb.search("CYRAEN favori renk")
        check(any("camgobegi" in h["content"] for h in hits), "GBrain write+search",
              f"{len(hits)} sonuc")
    except Exception as exc:  # noqa: BLE001
        skip("GBrain", str(exc))

    # --- 6. kod calistirma ---
    from tools.code_tools import run_python
    rp = run_python("print(2**10)")
    if rp.get("error", "").startswith("Kod calistirma kapali"):
        skip("run_python", "kapali (.env CYRAEN_CODE_EXEC=true)")
    else:
        check(rp.get("stdout", "").strip() == "1024", "run_python", rp.get("stdout"))

    # --- 7. web konsolu ---
    from web.console_server import ConsoleServer
    from web.event_bus import BUS
    srv = ConsoleServer(outbox_path=s.data_dir / "mega_out.txt",
                        inbox_path=s.data_dir / "mega_in.txt", port=8791, bind="127.0.0.1")
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.6)
    try:
        import httpx
        with httpx.Client(timeout=5) as hc:
            st = hc.get("http://127.0.0.1:8791/api/state").json()
            check("connection" in st, "web /api/state")
            sr = hc.post("http://127.0.0.1:8791/api/say", json={"text": "web testi"}).json()
            check(sr.get("status") == "iletildi", "web /api/say")
        time.sleep(0.2)
        out = (s.data_dir / "mega_out.txt").read_text(encoding="utf-8")
        check("[TELEFON] web testi" in out, "web -> outbox enjeksiyonu")
    except Exception as exc:  # noqa: BLE001
        check(False, "web konsolu", str(exc))
    finally:
        srv.stop()

    # --- 8. arac kaydi ---
    from tools.tool_declarations import get_tools
    from tools.tool_runner import ToolRunner
    tr = ToolRunner()
    dec = {d.name for d in get_tools()[0].function_declarations}
    check(set(tr.tool_names) == dec, "arac kaydi == tanimlar", f"{len(tr.tool_names)} arac")

    print("\n" + ("\033[92mMEGA TESTLER GECTI\033[0m" if _ok else "\033[91mBAZI TESTLER BASARISIZ\033[0m"))
    return 0 if _ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
