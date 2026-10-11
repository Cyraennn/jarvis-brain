"""EngineObserver / OrchestratorObserver -> web konsolu (BUS) koprusu, Qt olmadan.

`ui/qt_observer.py::QtEngineObserver` ve `agents/qt_observer.py::QtOrchestratorObserver`
ile ayni `BUS.push(...)` cagrilarini yapar (arayuz GUI'siz calisirken de /api/state ve
SSE dolu kalsin diye), ama `confirm()` bir Qt diyalogu yerine `web/confirm_registry.py`
uzerinden bloklar ve `web/console_server.py::POST /api/confirm` ile cozulur.

`run_server.py` (GUI'siz sunucu modu) bunlari kullanir; `ui/app.py` (masaustu) hala
Qt gozlemcilerini kullanmaya devam eder - burasi onlari DEGISTIRMEZ.
"""

from __future__ import annotations

from loguru import logger

from agents.events import OrchestratorObserver
from agents.schemas import DEPARTMENT_TITLES, AgentSpec, TaskUpdate
from core.events import EngineObserver
from web.confirm_registry import REGISTRY
from web.event_bus import BUS


def _await_confirmation(prompt: str, source: str, timeout: float) -> bool:
    pc = REGISTRY.create(prompt, source=source)
    logger.info(f"Uzak onay istegi ({source}): {prompt!r} (id={pc.id})")
    BUS.push("confirmation_request", pc.as_dict())
    answered = pc.wait(timeout)
    REGISTRY.discard(pc.id)
    approved = pc.result if answered else False
    BUS.push(
        "confirmation_resolved",
        {"id": pc.id, "approved": approved, "timed_out": not answered},
    )
    if not answered:
        logger.warning(f"Onay zaman asimina ugradi -> REDDEDILDI: {prompt!r}")
    return approved


class WebEngineObserver(EngineObserver):
    """`QtEngineObserver` ile ayni BUS olaylarini yayinlar, Qt sinyali olmadan."""

    def __init__(self, confirm_timeout: float = 120.0) -> None:
        self._confirm_timeout = confirm_timeout

    def on_connection(self, status: str) -> None:
        BUS.push("connection", status)

    def on_state(self, state: str) -> None:
        BUS.push("engine_state", state)

    def on_user_transcript(self, text: str, final: bool) -> None:
        if final and text.strip():
            BUS.push("transcript", {"who": "user", "text": text, "ts": 0})

    def on_assistant_transcript(self, text: str, final: bool) -> None:
        if final and text.strip():
            BUS.push("transcript", {"who": "jarvis", "text": text, "ts": 0})

    def on_tool_call(self, names: list[str]) -> None:
        BUS.push("tool_call", {"names": list(names)})

    def on_tool_result(self, name: str, ok: bool, detail: str) -> None:
        BUS.push("tool_result", {"name": name, "ok": bool(ok), "detail": detail})

    def on_bridge_message(self, text: str) -> None:
        BUS.push("bridge_message", text)

    def confirm(self, prompt: str) -> bool:
        return _await_confirmation(prompt, "engine", self._confirm_timeout)

    def on_exit_request(self) -> None:
        BUS.push("exit_request", True)


class WebOrchestratorObserver(OrchestratorObserver):
    """`QtOrchestratorObserver` ile ayni BUS olaylarini yayinlar, Qt sinyali olmadan."""

    def __init__(self, confirm_timeout: float = 120.0) -> None:
        self._confirm_timeout = confirm_timeout

    def on_agents_loaded(self, agents: list[AgentSpec]) -> None:
        BUS.push("agents_loaded", [
            {"name": a.name, "title": a.title,
             "department": getattr(a.department, "value", ""),
             "department_title": DEPARTMENT_TITLES.get(a.department, ""),
             "autonomy": getattr(a.autonomy, "value", ""), "status": "idle"}
            for a in agents
        ])

    def on_task(self, update: TaskUpdate) -> None:
        BUS.push("task", {
            "id": update.id, "agent": update.agent, "status": update.status,
            "department": update.department, "autonomy": update.autonomy,
            "detail": update.detail, "result": (update.result or "")[:200],
        })

    def confirm(self, prompt: str) -> bool:
        return _await_confirmation(prompt, "orchestrator", self._confirm_timeout)
