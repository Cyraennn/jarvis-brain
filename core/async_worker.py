"""Kalici asenkron kaynaklar icin tek arka plan event loop'u.

MCP oturumlari ve Playwright tarayicisi asenkron ve uzun omurlu; ama ajan
araclari `asyncio.to_thread` icinde senkron cagrilir. Ikisi de bu daemon
thread'deki loop'ta yasar, senkron sarmalayicilar `submit()` ile bekler.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from loguru import logger

T = TypeVar("T")


class AsyncWorker:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closers: list[Callable[[], Coroutine[Any, Any, Any]]] = []

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or not self._loop.is_running():
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def _run() -> None:
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()

                self._thread = threading.Thread(target=_run, name="cyraen-async-worker", daemon=True)
                self._thread.start()
                ready.wait(5)
                self._loop = loop
            return self._loop

    def submit(self, coro: Coroutine[Any, Any, T], timeout: float = 120.0) -> T:
        """Coroutine'i worker loop'unda calistirir ve sonucu senkron dondurur."""
        loop = self._ensure()
        if threading.current_thread() is self._thread:
            coro.close()
            raise RuntimeError("AsyncWorker.submit worker thread'inin icinden cagrilamaz")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    def on_shutdown(self, closer: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        """Kapanista worker loop'unda calisacak bir temizlik coroutine'i kaydeder."""
        self._closers.append(closer)

    def shutdown(self, timeout: float = 10.0) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _close_all() -> None:
            for closer in reversed(self._closers):
                try:
                    await closer()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"AsyncWorker kapanis hatasi: {exc!r}")

        try:
            asyncio.run_coroutine_threadsafe(_close_all(), loop).result(timeout)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"AsyncWorker kapanis zaman asimi: {exc!r}")
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout)
        with self._lock:
            self._loop = None
            self._thread = None


_worker: AsyncWorker | None = None


def get_worker() -> AsyncWorker:
    global _worker
    if _worker is None:
        _worker = AsyncWorker()
    return _worker
