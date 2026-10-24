"""Telefon uygulamasina eylem gonderme kanali (arama, SMS, alarm, konum...).

Akis: arac (`tools/phone_tools.py`) `PHONE.request(name, args)` cagirir -> veriyoluna
`phone_action {id, name, args}` yazilir -> telefon SSE'den alir, eylemi yapar ->
`POST /api/phone-result {id, ok, result|error}` -> `PHONE.resolve()` bekleyen araci uyandirir.

Telefon `GET /api/events?client=phone` ile baglaninca `attach()`, kopunca `detach()` olur;
bagli telefon yoksa istek hic yayinlanmaz, arac hemen hata doner (model uydurmasin diye).
Bekleme bloklayicidir: senkron araclar `ToolRunner` tarafindan zaten thread'de calisir.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from web.event_bus import BUS

DEFAULT_TIMEOUT = 25.0  # telefonda onay karti var: kullaniciya dusunme payi


@dataclass
class _Pending:
    name: str
    event: threading.Event = field(default_factory=threading.Event)
    reply: dict[str, Any] | None = None


class PhoneLink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients = 0
        self._pending: dict[str, _Pending] = {}

    # -------------------------------------------------------------- baglanti
    @property
    def connected(self) -> bool:
        return self._clients > 0

    def attach(self) -> None:
        with self._lock:
            self._clients += 1
        BUS.push("phone", {"connected": True})

    def detach(self) -> None:
        with self._lock:
            self._clients = max(0, self._clients - 1)
            left = self._clients
        if not left:
            BUS.push("phone", {"connected": False})

    # --------------------------------------------------------------- istekler
    def request(self, name: str, args: dict[str, Any] | None = None,
                timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        """Telefona eylemi gonderir, sonucunu bekler. Her zaman sozluk doner (hata da)."""
        if not self.connected:
            return {"error": "Telefon uygulamasi bagli degil; bu eylem yapilamaz."}
        req_id = uuid.uuid4().hex
        pending = _Pending(name)
        with self._lock:
            self._pending[req_id] = pending
        BUS.push("phone_action", {"id": req_id, "name": name, "args": args or {}})
        try:
            if not pending.event.wait(timeout):
                BUS.push("phone_action_expired", {"id": req_id})
                return {"error": f"Telefon {int(timeout)} sn icinde yanit vermedi."}
            return pending.reply or {"error": "bos yanit"}
        finally:
            with self._lock:
                self._pending.pop(req_id, None)

    def resolve(self, req_id: str, reply: dict[str, Any]) -> bool:
        """`POST /api/phone-result`. Bilinmeyen / suresi dolmus id icin False."""
        with self._lock:
            pending = self._pending.get(req_id)
        if pending is None:
            return False
        pending.reply = reply
        pending.event.set()
        return True


# Uygulama genelinde tek kanal (BUS / REGISTRY deseni)
PHONE = PhoneLink()
