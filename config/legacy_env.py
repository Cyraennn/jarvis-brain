"""Eski ad (JARVIS) ile yazilmis ortam degiskenlerini yeni ada (CYRAEN) tasir.

Asistanin adi JARVIS -> CYRAEN oldu; tum kod artik `CYRAEN_*` okur. Eski bir `.env`
(sunucu, lab paketi, uzak istemci) hala `JARVIS_*` icerebilir. `.env` yuklendikten
hemen sonra bu fonksiyon cagrilir: `CYRAEN_X` yoksa `JARVIS_X` degeri ona kopyalanir.
Yeni ad her zaman onceliklidir.
"""

from __future__ import annotations

import os

LEGACY_PREFIX = "JARVIS_"
PREFIX = "CYRAEN_"


def alias_legacy_env(environ: dict[str, str] | None = None) -> list[str]:
    """`JARVIS_*` -> `CYRAEN_*` (yalniz yeni ad tanimsizsa). Tasinan yeni adlari doner."""
    env = os.environ if environ is None else environ
    moved = []
    for key in list(env):
        if key.startswith(LEGACY_PREFIX):
            new = PREFIX + key[len(LEGACY_PREFIX):]
            if new not in env:
                env[new] = env[key]
                moved.append(new)
    return moved
