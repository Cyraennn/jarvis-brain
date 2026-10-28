"""ntfy.sh bildirimleri.

Topic verilirse `<server>/<topic>` adresine POST atar (masaustu/mobil bildirim).
Verilmezse sadece loglar. Hicbir zaman hata firlatmaz.
"""

from __future__ import annotations

import httpx
from loguru import logger


class Ntfy:
    def __init__(self, topic: str = "", server: str = "https://ntfy.sh") -> None:
        self.topic = (topic or "").strip()
        self.server = (server or "https://ntfy.sh").rstrip("/")
        self.enabled = bool(self.topic)
        if self.enabled:
            logger.info(f"ntfy bildirimleri aktif: {self.server}/{self.topic}")
        else:
            logger.info("ntfy topic yok -> bildirimler yalnizca loglanir")

    async def notify(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: list[str] | None = None,
        click: str = "",
    ) -> None:
        line = f"[ntfy] {title} - {message}"
        if not self.enabled:
            logger.info(line)
            return
        headers = {
            "Title": title.encode("utf-8", "ignore").decode("latin-1", "ignore") or "JARVIS",
            "Priority": str(priority),
        }
        if tags:
            headers["Tags"] = ",".join(tags)
        if click:
            headers["Click"] = click
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                await client.post(
                    f"{self.server}/{self.topic}",
                    content=message.encode("utf-8"),
                    headers=headers,
                )
            logger.info(line)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"ntfy bildirimi gonderilemedi: {exc!r}")
