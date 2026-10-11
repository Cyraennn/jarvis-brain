"""Harici ajan koprusu - outbox izleyici.

Harici ajanlar `bridge/outbox.txt` dosyasina satir satir mesaj yazar. Bu sinif
dosyayi 'tail -f' mantigiyla izler: yalnizca son okunan offset'ten sonra eklenen
satirlari asenkron olarak yayinlar. Dosya kirpilirsa / silinirse offset sifirlanir.
Baslangicta var olan eski birikim ATLANIR (yalnizca yeni mesajlar islenir).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from loguru import logger


class BridgeListener:
    def __init__(self, path: Path, poll_interval: float = 0.5) -> None:
        self._path = Path(path)
        self._poll = max(0.05, poll_interval)
        self._offset = 0

    async def messages(self, stop: "asyncio.Event | None" = None) -> AsyncIterator[str]:
        """Yeni koprulenen mesajlari yayinlar. `stop` verilirse set edilince biter."""
        await asyncio.to_thread(self._init_offset)
        logger.info(f"Kopru izleniyor: {self._path} (offset={self._offset}).")
        while stop is None or not stop.is_set():
            await asyncio.sleep(self._poll)
            lines = await asyncio.to_thread(self._read_new_lines)
            for line in lines:
                yield line

    # -------------------------------------------------------------- internal

    def _init_offset(self) -> None:
        try:
            self._offset = self._path.stat().st_size
        except OSError:
            self._offset = 0

    def _read_new_lines(self) -> list[str]:
        try:
            if not self._path.exists():
                self._offset = 0
                return []
            size = self._path.stat().st_size
        except OSError:
            return []

        if size < self._offset:  # dosya kirpildi / donduruldu
            self._offset = 0
        if size == self._offset:
            return []

        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except OSError as exc:
            logger.warning(f"Kopru dosyasi okunamadi: {exc!r}")
            return []

        return [line.strip() for line in chunk.splitlines() if line.strip()]
