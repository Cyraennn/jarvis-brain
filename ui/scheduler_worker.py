"""Zamanlayiciyi (SchedulerHandler) kendi thread'inde, kendi asyncio dongusuyle calistiran isci.

Arayuz (ui/app.py) ve server/__main__.py senkron/Qt tabanli oldugu icin SchedulerHandler'i
TaskGroup yerine bu thread'de calistirir. main.py ve run_server.py ise dogrudan TaskGroup'a ekler.
"""

from __future__ import annotations

import asyncio
import threading

from loguru import logger

from config.settings import Settings
from core.scheduler_handler import SchedulerHandler


class SchedulerWorker(threading.Thread):
    def __init__(self, settings: Settings) -> None:
        super().__init__(name="scheduler", daemon=True)
        self._settings = settings
        self._handler: SchedulerHandler | None = None

    def run(self) -> None:
        self._handler = SchedulerHandler(self._settings)
        try:
            asyncio.run(self._handler.run())
        except Exception:  # noqa: BLE001
            logger.exception("Zamanlayici sonlandi")

    def shutdown(self) -> None:
        if self._handler is not None:
            self._handler.request_shutdown()
