"""AgentOrchestrator'i kendi thread'inde calistiran isci (EngineWorker ile ayni desen)."""

from __future__ import annotations

import asyncio
import contextlib
import threading

from loguru import logger

from agents.events import OrchestratorObserver
from agents.orchestrator import AgentOrchestrator
from config.settings import Settings


class OrchestratorWorker(threading.Thread):
    def __init__(self, settings: Settings, observer: OrchestratorObserver) -> None:
        super().__init__(name="agent-orchestrator", daemon=True)
        self._settings = settings
        self._observer = observer
        self._loop: asyncio.AbstractEventLoop | None = None
        self._orch: AgentOrchestrator | None = None
        self._ready = threading.Event()

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._orch = AgentOrchestrator(self._settings, observer=self._observer)
        except Exception:  # noqa: BLE001
            logger.exception("Orkestrator baslatilamadi.")
            self._ready.set()
            return
        self._ready.set()
        try:
            self._loop.run_until_complete(self._orch.run())
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception:  # noqa: BLE001
            logger.exception("Orkestrator worker sonlandi.")
        finally:
            with contextlib.suppress(Exception):
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def shutdown(self) -> None:
        if self._orch is not None and self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._orch.request_shutdown)
