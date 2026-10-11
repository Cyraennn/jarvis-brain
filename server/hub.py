"""Bagli istemciler (PC, ileride robot) ile sunucu arasindaki merkez.

- Istemci kaydi: her istemci baglanirken calistirabilecegi eylemleri (`actions`) ve onay
  penceresi gosterip gosteremeyecegini (`confirm`) bildirir.
- `request_action`: bir eylemi, onu destekleyen bagli istemciye `action_request` olarak
  yollar ve `action_result`'i bekler. Uygun istemci yoksa `ClientUnavailable`.
- `request_action_blocking`: arac thread'lerinden (ToolRunner / ajanlar `asyncio.to_thread`
  icinde) cagrilir; sunucunun asyncio dongusune guvenle aktarir.
- Olaylar: `web/event_bus.py::BUS` olaylari + motorun canli olaylari (ses seviyesi, kismi
  transkript) tum istemcilere `event` mesaji olarak yayinlanir. Onay istekleri BUS'tan
  okunup onay gosterebilen istemcilere `confirm_request` olarak iletilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from loguru import logger

from remote.protocol import action_timeout, short_name
from web.confirm_registry import REGISTRY
from web.event_bus import BUS

SendFn = Callable[[dict[str, Any]], Awaitable[None]]


class ClientUnavailable(RuntimeError):
    """Eylemi yapabilecek bagli istemci yok / baglanti koptu."""


@dataclass
class ClientConn:
    name: str
    kind: str
    actions: set[str]
    confirm: bool
    send: SendFn
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "confirm": self.confirm,
            "actions": len(self.actions), "connected_at": self.connected_at,
            "last_seen": self.last_seen,
        }


class ClientHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[str, ClientConn] = {}
        self._pending: dict[str, tuple[asyncio.Future, str]] = {}   # istek id -> (future, client id)
        self._rr = itertools.count()
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._stream_state: dict[str, bool] = {"screen": False, "webcam": False}

    # --------------------------------------------------------------- dongu
    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    # --------------------------------------------------------------- kayit
    async def register(self, conn: ClientConn) -> None:
        self._clients[conn.id] = conn
        self._send_locks[conn.id] = asyncio.Lock()
        logger.bind(event="client_connected", client=conn.name).success(
            f"Istemci baglandi: {conn.name} ({conn.kind}, {len(conn.actions)} eylem, "
            f"onay={'evet' if conn.confirm else 'hayir'})"
        )
        BUS.push("client", {"connected": True, **conn.info()})
        await self._send(conn, {"type": "stream_control", **self._stream_state})
        # gec baglanan istemci bekleyen onaylari da gorsun
        if conn.confirm:
            for pc in REGISTRY.pending_list():
                await self._send(conn, {"type": "confirm_request", **pc})

    async def unregister(self, conn: ClientConn) -> None:
        self._clients.pop(conn.id, None)
        self._send_locks.pop(conn.id, None)
        for req_id, (fut, cid) in list(self._pending.items()):
            if cid == conn.id and not fut.done():
                fut.set_exception(ClientUnavailable(f"{conn.name} baglantisi koptu"))
                self._pending.pop(req_id, None)
        logger.bind(event="client_disconnected", client=conn.name).warning(
            f"Istemci ayrildi: {conn.name}"
        )
        BUS.push("client", {"connected": False, **conn.info()})

    def clients(self) -> list[dict[str, Any]]:
        return [c.info() for c in self._clients.values()]

    def pick(self, action: str) -> ClientConn | None:
        capable = [c for c in self._clients.values() if action in c.actions]
        if not capable:
            return None
        return capable[next(self._rr) % len(capable)]

    # --------------------------------------------------------------- gonderim
    async def _send(self, conn: ClientConn, msg: dict[str, Any]) -> bool:
        lock = self._send_locks.get(conn.id)
        if lock is None:
            return False
        try:
            async with lock:
                await conn.send(msg)
            return True
        except Exception as exc:  # noqa: BLE001 - kopuk baglanti yayini bozmaz
            logger.debug(f"{conn.name} istemcisine gonderilemedi: {exc!r}")
            return False

    async def broadcast(self, msg: dict[str, Any], *, confirm_only: bool = False) -> int:
        targets = [c for c in self._clients.values() if c.confirm or not confirm_only]
        results = await asyncio.gather(*(self._send(c, msg) for c in targets))
        return sum(1 for ok in results if ok)

    def publish_threadsafe(self, kind: str, data: Any = None) -> None:
        """Herhangi bir thread'den canli olay yayinla (BUS'a yazilmayan yuksek frekansli olaylar)."""
        loop = self._loop
        if loop is None or loop.is_closed() or not self._clients:
            return
        msg = {"type": "event", "kind": kind, "data": data, "ts": time.time()}
        try:
            loop.call_soon_threadsafe(lambda: loop.create_task(self.broadcast(msg)))
        except RuntimeError:
            pass  # dongu kapaniyor

    # --------------------------------------------------------------- eylemler
    async def request_action(
        self, action: str, args: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        conn = self.pick(action)
        if conn is None:
            raise ClientUnavailable(
                f"'{short_name(action)}' icin bagli istemci yok (PC kapali veya JARVIS istemcisi "
                "calismiyor). Bu islem sunucuda YAPILMAZ."
            )
        timeout = timeout or action_timeout(action)
        req_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = (fut, conn.id)
        logger.bind(event="action_request", action=action, client=conn.name).info(
            f"Eylem istegi -> {conn.name}: {short_name(action)}"
        )
        sent = await self._send(conn, {
            "type": "action_request", "id": req_id, "action": action,
            "args": args, "timeout": timeout,
        })
        if not sent:
            self._pending.pop(req_id, None)
            raise ClientUnavailable(f"{conn.name} istemcisine ulasilamadi")
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise ClientUnavailable(
                f"{conn.name} '{short_name(action)}' eylemine {timeout:.0f} sn icinde yanit vermedi"
            ) from None
        finally:
            self._pending.pop(req_id, None)

    def request_action_blocking(
        self, action: str, args: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        """Arac thread'inden cagrilir. Hata durumunda istisna yerine `{"error": ...}` doner."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return {"error": "Sunucu dongusu hazir degil."}
        if _running_loop() is loop:
            # dongu thread'inden bloklayarak beklemek kilitlenme demek - programlama hatasi
            return {"error": f"'{short_name(action)}' dongu thread'inden bloklayici cagrildi."}
        timeout = timeout or action_timeout(action)
        future = asyncio.run_coroutine_threadsafe(self.request_action(action, args, timeout), loop)
        try:
            result = future.result(timeout + 5)
        except ClientUnavailable as exc:
            logger.bind(event="action_unavailable", action=action).warning(str(exc))
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            future.cancel()
            return {"error": f"{type(exc).__name__}: {exc}"}
        return result if isinstance(result, dict) else {"result": result}

    def resolve_action(self, conn: ClientConn, msg: dict[str, Any]) -> None:
        entry = self._pending.get(str(msg.get("id", "")))
        if entry is None:
            return  # zaman asimi sonrasi gec gelen yanit
        fut, cid = entry
        if cid != conn.id or fut.done():
            return
        result = msg.get("result")
        if not isinstance(result, dict):
            result = {"result": result}
        if not msg.get("ok", False) and "error" not in result:
            result = {"error": str(result.get("result") or "istemci hatasi")}
        fut.set_result(result)

    # --------------------------------------------------------------- onay
    @staticmethod
    def resolve_confirm(msg: dict[str, Any]) -> bool:
        return REGISTRY.resolve(str(msg.get("id", "")), bool(msg.get("approved")))

    # --------------------------------------------------------------- akislar
    def set_stream_state(self, screen: bool, webcam: bool) -> bool:
        new = {"screen": bool(screen), "webcam": bool(webcam)}
        changed = new != self._stream_state
        self._stream_state = new
        return changed

    @property
    def stream_state(self) -> dict[str, bool]:
        return dict(self._stream_state)

    # --------------------------------------------------------------- BUS pompasi
    async def pump_bus(self, stop: asyncio.Event, interval: float = 0.1) -> None:
        """BUS olaylarini istemcilere tasir; onay isteklerini ozel mesaja cevirir."""
        q = BUS.subscribe()
        try:
            while not stop.is_set():
                while q:
                    evt = q.popleft()
                    kind, data = evt.get("kind"), evt.get("data")
                    if kind == "confirmation_request":
                        n = await self.broadcast({"type": "confirm_request", **(data or {})},
                                                 confirm_only=True)
                        if n == 0:
                            logger.warning("Onay istegi var ama onay gosterebilen bagli istemci yok "
                                           "(web konsolundan da onaylanabilir).")
                    elif kind == "confirmation_resolved":
                        await self.broadcast({"type": "confirm_resolved", **(data or {})},
                                             confirm_only=True)
                    await self.broadcast({"type": "event", "kind": kind, "data": data,
                                          "ts": evt.get("ts")})
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=interval)
        finally:
            BUS.unsubscribe(q)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
