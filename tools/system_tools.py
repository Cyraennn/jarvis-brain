"""Sistem / surec araclari - stdlib (tasklist/ps ayristirmasi)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any


def list_processes(top_n: int = 12) -> dict[str, Any]:
    """En cok bellek kullanan surecleri listeler (ad + bellek)."""
    try:
        top_n = max(1, min(50, int(top_n)))
    except (TypeError, ValueError):
        top_n = 12
    procs: list[dict[str, Any]] = []
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout
            for line in out.splitlines():
                parts = [p.strip('" ') for p in line.split('","')]
                if len(parts) < 5:
                    continue
                name = parts[0]
                mem_kb = int(parts[4].replace(".", "").replace(",", "").replace(" K", "") or 0)
                procs.append({"name": name, "pid": parts[1], "mem_mb": round(mem_kb / 1024, 1)})
        else:
            out = subprocess.run(
                ["ps", "-eo", "comm,pid,rss", "--sort=-rss"],
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout
            for line in out.splitlines()[1:]:
                f = line.split()
                if len(f) >= 3:
                    procs.append({"name": f[0], "pid": f[1], "mem_mb": round(int(f[2]) / 1024, 1)})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Surec listesi alinamadi: {exc}"}

    # ada gore birlestir
    agg: dict[str, dict[str, Any]] = {}
    for p in procs:
        e = agg.setdefault(p["name"], {"name": p["name"], "count": 0, "mem_mb": 0.0})
        e["count"] += 1
        e["mem_mb"] = round(e["mem_mb"] + p["mem_mb"], 1)
    ranked = sorted(agg.values(), key=lambda e: -e["mem_mb"])[:top_n]
    return {"count": len(agg), "top": ranked}


def kill_process(name: str) -> dict[str, Any]:
    """Bir uygulamayi/sureci kapatir (NAZIK, /F yok). ToolRunner bunu onay kapisina baglar."""
    from tools.window_control import close_application, resolve_close_target

    target = resolve_close_target(name)
    if not target.get("ok"):
        return {"error": target.get("error", "cozulemedi")}
    return close_application(target)
