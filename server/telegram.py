"""Kritik hata bildirimi: Telegram botu (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).

Tanimli degilse yalnizca loglanir. Ayni mesaj `DEDUPE_S` icinde tekrar gonderilmez,
saatte en fazla `MAX_PER_HOUR` mesaj gider (dongude hata = bildirim yagmuru olmasin).
Gonderim ayri bir thread'de yapilir; model cagrisini / motoru asla bekletmez.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import httpx
from loguru import logger

DEDUPE_S = 600.0
MAX_PER_HOUR = 20


class TelegramNotifier:
    def __init__(self, bot_token: str = "", chat_id: str = "", *, prefix: str = "CYRAEN") -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.prefix = prefix
        self._lock = threading.Lock()
        self._last_sent: dict[str, float] = {}
        self._sent_times: deque[float] = deque()
        self.sent_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _allowed(self, text: str) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._sent_times and now - self._sent_times[0] > 3600:
                self._sent_times.popleft()
            if len(self._sent_times) >= MAX_PER_HOUR:
                return False
            key = text[:160]
            if now - self._last_sent.get(key, -1e9) < DEDUPE_S:
                return False
            self._last_sent[key] = now
            self._sent_times.append(now)
            return True

    def notify(self, text: str) -> bool:
        """Bildirim kuyruga alinirsa True. Yapilandirilmamissa sadece loglar."""
        text = f"⚠️ {self.prefix}: {text}"[:3500]
        if not self.enabled:
            logger.bind(event="alert", telegram=False).warning(f"[BILDIRIM - Telegram yok] {text}")
            return False
        if not self._allowed(text):
            logger.debug("Telegram bildirimi sinir/dedupe nedeniyle atlandi.")
            return False
        threading.Thread(target=self._send, args=(text,), name="telegram", daemon=True).start()
        return True

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = httpx.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10.0)
            if resp.status_code != 200:
                # token URL'de oldugu icin ASLA url/istisna metninin tamamini loglama
                logger.warning(f"Telegram bildirimi basarisiz: HTTP {resp.status_code}")
            else:
                self.sent_count += 1
        except httpx.HTTPError as exc:
            logger.warning(f"Telegram bildirimi gonderilemedi: {type(exc).__name__}")

    def loguru_sink(self, message) -> None:  # noqa: ANN001
        """logger.add(notifier.loguru_sink, level='CRITICAL') ile kullanilir."""
        record = message.record
        self.notify(f"{record['level'].name}: {record['message']}")
