"""Motor/orkestratorden gelen onay isteklerini web konsoluna tasiyan paylasilan kayit defteri.

`web/web_observer.py::WebEngineObserver.confirm()` (motor) ve
`web/web_observer.py::WebOrchestratorObserver.confirm()` (ajan orkestratoru) burada bir
`PendingConfirmation` olusturup BLOKLAYARAK bekler; `web/console_server.py::POST /api/confirm`
ayni id'yi bulup `resolve()` cagirir. Zaman asiminda REDDEDILIR (headless/paylasimli
makinede bilincli guvenlik varsayilani - otomatik onay YOK).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class PendingConfirmation:
    id: str
    prompt: str
    source: str = "engine"  # "engine" | "orchestrator"
    requested_at: float = field(default_factory=time.time)
    result: bool = False
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def resolve(self, approved: bool) -> None:
        self.result = bool(approved)
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "source": self.source,
            "requested_at": self.requested_at,
        }


class ConfirmRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingConfirmation] = {}

    def create(self, prompt: str, source: str = "engine") -> PendingConfirmation:
        pc = PendingConfirmation(id=uuid.uuid4().hex, prompt=prompt, source=source)
        with self._lock:
            self._pending[pc.id] = pc
        return pc

    def resolve(self, conf_id: str, approved: bool) -> bool:
        """id eslesirse cozer ve True doner; bilinmeyen/suresi dolmus id icin False."""
        with self._lock:
            pc = self._pending.get(conf_id)
        if pc is None:
            return False
        pc.resolve(approved)
        return True

    def discard(self, conf_id: str) -> None:
        with self._lock:
            self._pending.pop(conf_id, None)

    def pending_list(self) -> list[dict]:
        with self._lock:
            return [pc.as_dict() for pc in self._pending.values()]


# Uygulama genelinde tek kayit defteri (BUS deseniyle ayni - web/event_bus.py::BUS)
REGISTRY = ConfirmRegistry()
