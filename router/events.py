"""Router olay yolu: routing.jsonl'a yazilan her satir (decision / done / qa) canli
dinleyicilere de (Decision Pipeline panosu, /ws/decisions) yayinlanir.

Yayinci (orkestrator thread'i) ile dinleyiciler (pano sunucusunun event loop'u) farkli
thread'lerdedir: teslim `loop.call_soon_threadsafe` ile yapilir. Yavas dinleyici yayinciyi
ASLA bekletmez: kuyrugu doluysa en eski olay atilir.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

QUEUE_SIZE = 500


class DecisionBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def subscribe(self) -> asyncio.Queue:
        """Calisan event loop icinden cagrilir; olaylari bu kuyruktan oku."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subs.append((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(lp, q) for lp, q in self._subs if q is not queue]

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    @staticmethod
    def _offer(queue: asyncio.Queue, event: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()   # en eskiyi at; yayinci beklemez
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    def publish(self, event: dict[str, Any]) -> None:
        """Herhangi bir thread'den cagrilabilir; hata firlatmaz."""
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:   # dinleyicinin loop'u kapanmis
                self.unsubscribe(queue)


BUS = DecisionBus()
