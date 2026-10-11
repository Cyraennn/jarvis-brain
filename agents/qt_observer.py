"""OrchestratorObserver -> Qt sinyal koprusu (brain-map + ajan paneli + onay)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from agents.events import OrchestratorObserver
from agents.schemas import DEPARTMENT_TITLES, AgentSpec, TaskUpdate
from web.event_bus import BUS


class ApprovalRequest:
    __slots__ = ("prompt", "_event", "result", "expired")

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self.result = False
        self.expired = False   # motor tarafi zaman asimiyla vazgecti (sonuc artik kullanilmaz)
        self._event = threading.Event()

    def resolve(self, approved: bool) -> None:
        self.result = bool(approved)
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class QtOrchestratorObserver(QObject, OrchestratorObserver):
    agents_loaded = Signal(list)     # list[AgentSpec]
    task = Signal(object)            # TaskUpdate
    approval_requested = Signal(object)  # ApprovalRequest

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        self._timeout = 120.0

    def on_agents_loaded(self, agents: list[AgentSpec]) -> None:
        self.agents_loaded.emit(list(agents))
        BUS.push("agents_loaded", [
            {"name": a.name, "title": a.title,
             "department": getattr(a.department, "value", ""),
             "department_title": DEPARTMENT_TITLES.get(a.department, ""),
             "autonomy": getattr(a.autonomy, "value", ""), "status": "idle"}
            for a in agents
        ])

    def on_task(self, update: TaskUpdate) -> None:
        self.task.emit(update)
        BUS.push("task", {
            "id": update.id, "agent": update.agent, "status": update.status,
            "department": update.department, "autonomy": update.autonomy,
            "detail": update.detail, "result": (update.result or "")[:200],
        })

    def confirm(self, prompt: str) -> bool:
        req = ApprovalRequest(prompt)
        self.approval_requested.emit(req)
        if not req.wait(self._timeout):
            req.expired = True  # GUI diyalogu bunu gorup kendini kapatir
            return False
        return req.result
