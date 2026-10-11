"""Internet yoklamasi - cevrimdisiyken bulut modelleri hic denenmesin diye.

Gemini API ucuna kisa bir TCP baglantisi acilir; cevrimdisi makinede DNS hemen
duser, yani yoklama genelde milisaniyeler surer (en fazla PROBE_TIMEOUT_S).
Sonuc onbellege alinir; durum degisince (cevrimici <-> cevrimdisi) bir kez loglanir.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger

PROBE_HOST = "generativelanguage.googleapis.com"
PROBE_PORT = 443
PROBE_TIMEOUT_S = 2.0
ONLINE_TTL_S = 15.0
OFFLINE_TTL_S = 5.0

_state: bool | None = None  # son bilinen durum (None = hic yoklanmadi)
_checked_at = 0.0


async def _probe() -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(PROBE_HOST, PROBE_PORT), timeout=PROBE_TIMEOUT_S
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def is_online(force: bool = False) -> bool:
    """Internet var mi (onbellekli: cevrimici 15 sn, cevrimdisi 5 sn)."""
    global _state, _checked_at
    now = time.monotonic()
    if not force and _state is not None:
        ttl = ONLINE_TTL_S if _state else OFFLINE_TTL_S
        if now - _checked_at < ttl:
            return _state
    online = await _probe()
    if online != _state:
        if not online:
            logger.bind(event="connectivity", online=False).warning(
                "CEVRIMDISI: internet yok - bulut modelleri atlaniyor, yerel model kullanilacak"
            )
        elif _state is False:
            logger.bind(event="connectivity", online=True).info("Internet geri geldi")
    _state, _checked_at = online, time.monotonic()
    return online
