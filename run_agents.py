"""Cok-ajanli orkestratoru tek basina calistirir (sesli beyin olmadan).

    python run_agents.py

bridge/inbox.txt'e yazilan gorevleri isler, sonuclari bridge/outbox.txt'e yazar.
Canli beyin (main.py / run_ui.py) ile ayni anda calisabilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from loguru import logger

from agents.orchestrator import AgentOrchestrator
from config.settings import get_settings


async def _amain() -> None:
    settings = get_settings()
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, level=settings.log_level,
                   format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    logger.add(settings.data_dir / "agents.log", level="DEBUG", rotation="10 MB", retention=5,
               encoding="utf-8")

    orchestrator = AgentOrchestrator(settings)

    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, orchestrator.request_shutdown)

    await orchestrator.run()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("Kapatiliyor.")


if __name__ == "__main__":
    main()
