"""Proaktif bildirim dagiticisi - tek cagriyla tum aktif kanallara (Telegram/WhatsApp/ntfy/ses).

Kanallar `register(name, sender)` ile eklenir; `sender` bir async callable'dir:
    async def sender(text: str) -> bool
Her kanal ayri try/except + zaman asimi icinde calisir: biri cokerse digerleri etkilenmez.

Varsayilan kurulum `build_broadcaster()` ile yapilir; ayarlarda tanimli olmayan
kanallar (token yok, handler yok) hic kaydedilmez.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from loguru import logger

from core.bridge_mirror import mirror_to_bridge

Sender = Callable[[str], Awaitable[bool]]

SEND_TIMEOUT_S = 60.0


class NotificationBroadcaster:
    """Kanal adi -> async gonderici. `broadcast` sonucu {kanal: basarili_mi} doner."""

    def __init__(self) -> None:
        self._channels: dict[str, Sender] = {}

    def register(self, name: str, sender: Sender) -> None:
        self._channels[name] = sender
        logger.debug(f"Bildirim kanali kaydedildi: {name}")

    @property
    def channels(self) -> list[str]:
        return list(self._channels)

    async def broadcast(self, text: str, channels: list[str] | None = None) -> dict[str, bool]:
        """Metni secili (bos ise tum) kanallara paralel gonderir; hata asla yukari tasinmaz."""
        text = (text or "").strip()
        if not text:
            return {}
        names = [c for c in (channels or self.channels) if c in self._channels]
        if not names:
            logger.info("Bildirim gonderilecek aktif kanal yok.")
            return {}
        results = await asyncio.gather(*(self._send_one(n, text) for n in names))
        outcome = dict(zip(names, results))
        logger.info(f"Proaktif bildirim -> {outcome}")
        return outcome

    async def _send_one(self, name: str, text: str) -> bool:
        try:
            return bool(await asyncio.wait_for(self._channels[name](text), timeout=SEND_TIMEOUT_S))
        except asyncio.TimeoutError:
            logger.warning(f"Bildirim kanali zaman asimi: {name}")
        except Exception:  # noqa: BLE001 - tek kanal digerlerini bozmaz
            logger.exception(f"Bildirim kanali hatasi: {name}")
        return False


def build_broadcaster(
    settings: Any,
    *,
    telegram: Any = None,
    whatsapp: Any = None,
) -> NotificationBroadcaster:
    """Ayarlara ve verilen handler'lara gore kanallari kaydeder.

    - ``voice``   : bridge/outbox.txt -> CYRAEN canli oturumda sesli soyler (her zaman)
    - ``telegram``: TELEGRAM_BOT_TOKEN + varsayilan sohbet varsa (handler calismasa da;
                    Bot API durumsuzdur)
    - ``whatsapp``: calisan bir WhatsAppHandler verilmisse, yonetici numaralarina
    - ``ntfy``    : NTFY_TOPIC tanimliysa (telefon bildirimi)
    """
    b = NotificationBroadcaster()

    async def _voice(text: str) -> bool:
        mirror_to_bridge(f"[PROAKTIF] {text}", settings.bridge_outbox_path)
        return True

    b.register("voice", _voice)

    if settings.telegram_bot_token and settings.telegram_default_chat_id:
        if telegram is None:
            from core.telegram_handler import TelegramHandler

            telegram = TelegramHandler(settings)
        tg = telegram

        async def _telegram(text: str) -> bool:
            return await tg.send_proactive_message(None, text)

        b.register("telegram", _telegram)

    if whatsapp is not None and getattr(getattr(whatsapp, "cfg", None), "enabled", False):
        wa = whatsapp
        targets = list(getattr(wa.cfg, "admin_numbers", []) or [])
        if targets:
            async def _whatsapp(text: str) -> bool:
                oks = [await wa.send_proactive_message(t, text) for t in targets]
                return any(oks)

            b.register("whatsapp", _whatsapp)
        else:
            logger.info("WhatsApp proaktif kanal atlandi: config'de admin_numbers yok.")

    if settings.ntfy_topic:
        from agents.integrations.notifier import Notifier

        notifier = Notifier(settings.ntfy_topic, settings.ntfy_server)

        async def _ntfy(text: str) -> bool:
            await notifier.notify("CYRAEN", text[:1000], priority=3, tags=["robot"])
            return True

        b.register("ntfy", _ntfy)

    return b
