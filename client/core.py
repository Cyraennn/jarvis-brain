"""Genel JARVIS istemci cekirdegi - PC, robot ya da baska bir "govde" icin ayni.

    client = JarvisClient(url, token, name="robot-1", kind="robot")
    client.register("robot.move", move_handler)          # eylem handler'i (sync ya da async)
    client.on_event("engine_state", lambda data: ...)    # sunucu olaylarini dinle
    client.set_confirm_handler(ask_user)                  # onay isteklerini goster (opsiyonel)
    await client.run()                                    # koparsa ustel geri cekilmeyle yeniden baglanir

- Kimlik dogrulama: baglanti kurulunca ILK mesaj {"type":"auth","token":..}.
- Handler'lar thread'de (sync) ya da dongude (async) calisir; sonuc dict olarak dondurulur,
  istisnalar {"error": ...} olur - istemci asla cokmez.
- Sunucu, istemcinin kayit ettigi eylemlerin DISINDA bir sey isteyemez; kayitsiz eylem
  istegi hata ile yanitlanir.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import random
import uuid
from typing import Any, Awaitable, Callable

from loguru import logger
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from remote.protocol import MAX_MESSAGE_BYTES

Handler = Callable[..., Any]
EventListener = Callable[[Any], Any]
ConfirmHandler = Callable[[str, str], "bool | Awaitable[bool]"]

AUTH_REJECTED_CODE = 4401


class AuthRejected(RuntimeError):
    """Sunucu token'i reddetti - yeniden denemek anlamsiz."""


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """1, 2, 4, 8 ... en fazla `cap` sn + %25'e kadar rastgele sapma (surekli ayni anda denemesin)."""
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    return delay + random.uniform(0, delay * 0.25)


class JarvisClient:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        name: str = "istemci",
        kind: str = "generic",
        max_backoff: float = 30.0,
    ) -> None:
        self.url = url
        self.token = token
        self.name = name
        self.kind = kind
        self.max_backoff = max_backoff
        self._handlers: dict[str, Handler] = {}
        self._listeners: dict[str, list[EventListener]] = {}
        self._confirm: ConfirmHandler | None = None
        self._ws: ClientConnection | None = None
        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._pending_commands: dict[str, asyncio.Future] = {}
        self.connected = asyncio.Event()
        self.client_id: str | None = None
        self.connect_count = 0

    # ------------------------------------------------------------------ kayit
    def register(self, action: str, handler: Handler) -> None:
        self._handlers[action] = handler

    def action(self, name: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.register(name, fn)
            return fn
        return deco

    @property
    def actions(self) -> list[str]:
        return sorted(self._handlers)

    def on_event(self, kind: str, listener: EventListener) -> None:
        """kind='*' tum olaylari dinler (listener(evt_dict)); aksi halde listener(data)."""
        self._listeners.setdefault(kind, []).append(listener)

    def set_confirm_handler(self, handler: ConfirmHandler | None) -> None:
        self._confirm = handler

    # ------------------------------------------------------------------ gonderim
    async def send(self, msg: dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            async with self._send_lock:
                await ws.send(json.dumps(msg, ensure_ascii=False, default=str))
            return True
        except ConnectionClosed:
            return False

    async def send_frame(self, source: str, jpeg: bytes) -> bool:
        return await self.send({"type": "frame", "source": source,
                                "jpeg_b64": base64.b64encode(jpeg).decode("ascii")})

    async def control(self, action: str) -> bool:
        return await self.send({"type": "control", "action": action})

    async def command(self, text: str, timeout: float = 120.0) -> dict[str, Any]:
        """Sunucuya yazili komut gonder, command_result'i bekle."""
        cid = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_commands[cid] = fut
        try:
            if not await self.send({"type": "command", "id": cid, "text": text}):
                return {"ok": False, "error": "sunucuya bagli degil"}
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"{timeout:.0f} sn icinde yanit yok"}
        finally:
            self._pending_commands.pop(cid, None)

    # ------------------------------------------------------------------ yasam dongusu
    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            asyncio.get_event_loop().create_task(ws.close())

    async def run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._session()
                attempt = 0            # duzgun kapandi -> hemen tekrar dene
            except AuthRejected as exc:
                logger.critical(f"Sunucu kimligi reddetti: {exc}. Token'i kontrol edin; duruluyor.")
                return
            except (OSError, ConnectionClosed, InvalidStatus, asyncio.TimeoutError) as exc:
                attempt += 1
                logger.warning(f"Sunucu baglantisi yok/koptu ({type(exc).__name__}: {exc})")
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                logger.exception(f"Beklenmeyen istemci hatasi: {exc!r}")
            if self._stop.is_set():
                break
            delay = backoff_delay(max(1, attempt), cap=self.max_backoff)
            logger.info(f"{delay:.1f} sn sonra yeniden baglanilacak (deneme {attempt}).")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)

    async def _session(self) -> None:
        async with connect(self.url, max_size=MAX_MESSAGE_BYTES, open_timeout=15,
                           ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({
                "type": "auth", "token": self.token,
                "client": {"name": self.name, "kind": self.kind, "actions": self.actions,
                           "confirm": self._confirm is not None},
            }))
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if first.get("type") != "hello":
                raise AuthRejected(first.get("error") or "gecersiz yanit")
            self._ws = ws
            self.client_id = first.get("client_id")
            self.connect_count += 1
            self.connected.set()
            logger.success(f"Sunucuya baglanildi: {self.url} (istemci {self.client_id}, "
                           f"{len(self._handlers)} eylem)")
            await self._emit("connected", {"client_id": self.client_id})
            tasks: set[asyncio.Task] = set()
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    task = self._handle(msg)
                    if task is not None:
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
            except ConnectionClosed as exc:
                if exc.rcvd is not None and exc.rcvd.code == AUTH_REJECTED_CODE:
                    raise AuthRejected(exc.rcvd.reason) from exc
                raise
            finally:
                self._ws = None
                self.connected.clear()
                for t in tasks:
                    t.cancel()
                for fut in self._pending_commands.values():
                    if not fut.done():
                        fut.set_result({"ok": False, "error": "baglanti koptu"})
                await self._emit("disconnected", None)

    # ------------------------------------------------------------------ mesajlar
    def _handle(self, msg: dict[str, Any]) -> asyncio.Task | None:
        kind = msg.get("type")
        if kind == "action_request":
            return asyncio.create_task(self._run_action(msg))
        if kind == "confirm_request":
            return asyncio.create_task(self._run_confirm(msg))
        if kind == "command_result":
            fut = self._pending_commands.get(str(msg.get("id")))
            if fut is not None and not fut.done():
                fut.set_result(msg)
        elif kind == "event":
            return asyncio.create_task(self._emit(str(msg.get("kind")), msg.get("data"), msg))
        elif kind in ("stream_control", "confirm_resolved"):
            return asyncio.create_task(self._emit(kind, msg))
        elif kind == "error":
            logger.warning(f"Sunucu hatasi: {msg.get('error')}")
        return None

    async def _run_action(self, msg: dict[str, Any]) -> None:
        req_id, action = msg.get("id"), str(msg.get("action") or "")
        args = msg.get("args") or {}
        handler = self._handlers.get(action)
        if handler is None:
            await self.send({"type": "action_result", "id": req_id, "ok": False,
                             "result": {"error": f"Bu istemci '{action}' eylemini desteklemiyor."}})
            return
        logger.info(f"Eylem: {action.rsplit('.', 1)[-1]} {_preview(args)}")
        try:
            if inspect.iscoroutinefunction(handler):
                result = await handler(**args)
            else:
                result = await asyncio.to_thread(lambda: handler(**args))
                if inspect.isawaitable(result):
                    result = await result
            ok = not (isinstance(result, dict) and "error" in result)
        except TypeError as exc:
            result, ok = {"error": f"Gecersiz argumanlar: {exc}"}, False
        except Exception as exc:  # noqa: BLE001 - handler hatasi istemciyi cokertemez
            logger.exception(f"Eylem hatasi: {action}")
            result, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
        if not isinstance(result, dict):
            result = {"result": result}
        await self.send({"type": "action_result", "id": req_id, "ok": ok, "result": result})

    async def _run_confirm(self, msg: dict[str, Any]) -> None:
        handler = self._confirm
        if handler is None:
            return
        prompt, source = str(msg.get("prompt") or ""), str(msg.get("source") or "")
        try:
            if inspect.iscoroutinefunction(handler):
                approved = await handler(prompt, source)
            else:
                approved = await asyncio.to_thread(handler, prompt, source)
        except Exception:  # noqa: BLE001
            logger.exception("Onay penceresi hatasi -> REDDEDILDI")
            approved = False
        await self.send({"type": "confirm_response", "id": msg.get("id"), "approved": bool(approved)})

    async def _emit(self, kind: str, data: Any, raw: dict[str, Any] | None = None) -> None:
        for listener in [*self._listeners.get(kind, []), *self._listeners.get("*", [])]:
            arg = (raw or {"kind": kind, "data": data}) if listener in self._listeners.get("*", []) else data
            try:
                result = listener(arg)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.exception(f"Olay dinleyicisi hatasi: {kind}")


def _preview(args: dict[str, Any]) -> str:
    text = json.dumps(args, ensure_ascii=False, default=str)
    return text if len(text) <= 120 else text[:117] + "..."
