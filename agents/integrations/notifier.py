"""Birlesik bildirim - ntfy + web konsolu (SSE) fan-out.

`AgentOrchestrator` ve `Scheduler` `notifier.notify(...)` cagirir; hedeflerden biri
yapilandirilmamissa sessizce atlanir.
"""

from __future__ import annotations

from loguru import logger

from agents.integrations.ntfy import Ntfy


class Notifier:
    def __init__(self, ntfy_topic: str = "", ntfy_server: str = "https://ntfy.sh") -> None:
        self.ntfy = Ntfy(ntfy_topic, ntfy_server)

    async def notify(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: list[str] | None = None,
        click: str = "",
    ) -> None:
        try:
            await self.ntfy.notify(title, message, priority=priority, tags=tags, click=click)
        except Exception:  # noqa: BLE001
            logger.debug("ntfy notify hatasi")
        try:
            from web.event_bus import BUS

            BUS.push("transcript", {"who": "sys", "text": f"{title} — {message}", "ts": 0})
        except Exception:  # noqa: BLE001
            pass
