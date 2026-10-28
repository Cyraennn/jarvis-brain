"""Gecici ad (CYRAEN) ile yazilmis ortam degiskenlerini asil ada (JARVIS) tasir.

Asistanin adi kisa bir sure CYRAEN oldu, sonra yeniden JARVIS'e dondu; tum kod `JARVIS_*`
okur. O donemde yazilmis bir `.env` (sunucu, lab paketi, uzak istemci) hala `CYRAEN_*`
icerebilir. `.env` yuklendikten hemen sonra bu fonksiyon cagrilir: `JARVIS_X` yoksa
`CYRAEN_X` degeri ona kopyalanir.
Yeni ad her zaman onceliklidir.
"""

from __future__ import annotations

import os

LEGACY_PREFIX = "CYRAEN_"
PREFIX = "JARVIS_"


def alias_legacy_env(environ: dict[str, str] | None = None) -> list[str]:
    """`CYRAEN_*` -> `JARVIS_*` (yalniz yeni ad tanimsizsa). Tasinan yeni adlari doner."""
    env = os.environ if environ is None else environ
    moved = []
    for key in list(env):
        if key.startswith(LEGACY_PREFIX):
            new = PREFIX + key[len(LEGACY_PREFIX):]
            if new not in env:
                env[new] = env[key]
                moved.append(new)
    return moved
