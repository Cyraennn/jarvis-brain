"""Web konsolunu kendi thread'inde calistiran isci."""

from __future__ import annotations

import threading
from typing import Callable

from loguru import logger

from config.settings import Settings
from web.console_server import ConsoleServer


class WebWorker(threading.Thread):
    def __init__(
        self,
        settings: Settings,
        on_control: "Callable[[str], dict] | None" = None,
    ) -> None:
        super().__init__(name="web-console", daemon=True)
        self._settings = settings
        self._on_control = on_control
        self._server: ConsoleServer | None = None

    def run(self) -> None:
        s = self._settings
        self._server = ConsoleServer(
            outbox_path=s.agent_outbox_path,
            inbox_path=s.agent_inbox_path,
            port=s.web_console_port,
            bind=s.web_console_bind,
            token=s.web_console_token,
            on_control=self._on_control,
            okul_state_path=s.okul_state_path if s.okul_enabled else None,
            okul_outbox_path=s.okul_outbox_path if s.okul_enabled else None,
            team_tts=s.team_tts_enabled,
        )
        try:
            self._server.serve_forever()
        except Exception:  # noqa: BLE001
            logger.exception("Web konsolu sonlandi")

    @property
    def url(self) -> str:
        return self._server.url() if self._server else ""

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.stop()
