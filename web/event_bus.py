"""Thread-safe olay veriyolu - motor/orkestrator/zamanlayici olaylarini web konsoluna tasir.

Observer'lar `bus.push(kind, data)` cagirir. Web konsolu:
  - `bus.snapshot()` ile anlik durumu alir (/api/state)
  - `bus.subscribe()` ile SSE akisi dinler (/api/events)
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=history)
        self._subscribers: list[deque[dict[str, Any]]] = []
        self._seq = 0
        self.state: dict[str, Any] = {
            "connection": "connecting",
            "engine_state": "idle",
            "speaking": False,
            "mic": True,
            "screen": True,
            "away": False,             # "uzak mod" - telefondan gorusme
            "wake": False,             # uyandirma kelimesi ("Hey CYRAEN") acik mi
            "transcript": [],          # [{who, text, ts}]
            "agents": {},              # name -> {title, department, autonomy, status}
            "departments": [],
            "tasks": [],               # son gorev guncellemeleri
            "reminders": [],
            "routines": [],
            "confirmations": [],       # bekleyen onay istekleri [{id,prompt,source,requested_at}]
            "panel": None,             # acik icerik paneli (telefon uygulamasi icin)
            "started_at": time.time(),
        }

    # ------------------------------------------------------------------ yayin
    def push(self, kind: str, data: Any = None) -> None:
        with self._lock:
            self._seq += 1
            evt = {"seq": self._seq, "kind": kind, "data": data, "ts": time.time()}
            self._events.append(evt)
            self._apply(kind, data)
            for q in self._subscribers:
                q.append(evt)

    def _apply(self, kind: str, data: Any) -> None:
        s = self.state
        if kind == "connection":
            s["connection"] = data
        elif kind == "engine_state":
            s["engine_state"] = data
            s["speaking"] = data == "speaking"
        elif kind == "io":
            s.update({k: data[k] for k in ("mic", "screen") if k in (data or {})})
        elif kind == "control_state":
            s.update({k: (data or {})[k] for k in ("mic", "away", "wake") if k in (data or {})})
        elif kind == "transcript":
            s["transcript"].append(data)
            s["transcript"] = s["transcript"][-60:]
        elif kind == "agents_loaded":
            s["agents"] = {a["name"]: a for a in (data or [])}
            s["departments"] = sorted({a.get("department", "") for a in (data or [])} - {""})
        elif kind == "task":
            name = (data or {}).get("agent", "")
            if name in s["agents"]:
                s["agents"][name]["status"] = data.get("status", "")
            s["tasks"].insert(0, data)
            s["tasks"] = s["tasks"][:40]
        elif kind == "reminders":
            s["reminders"] = data or []
        elif kind == "routines":
            s["routines"] = data or []
        elif kind == "confirmation_request":
            s["confirmations"].append(data)
        elif kind == "confirmation_resolved":
            conf_id = (data or {}).get("id")
            s["confirmations"] = [c for c in s["confirmations"] if c.get("id") != conf_id]
        elif kind == "remote_audio":
            s["remote_audio"] = data or {}
        elif kind == "persona":
            s["persona"] = data or "cyraen"
        elif kind == "panel":
            # telefon sonradan baglanirsa acik paneli /api/state'ten alir
            pkind = (data or {}).get("kind")
            if pkind == "close":
                s["panel"] = None
            elif pkind != "map_control":
                s["panel"] = data

    # -------------------------------------------------------------- abonelik
    def subscribe(self) -> deque[dict[str, Any]]:
        q: deque[dict[str, Any]] = deque(maxlen=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: deque) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self.state, default=str))


# Uygulama genelinde tek veriyolu
BUS = EventBus()
