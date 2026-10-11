"""Supabase gorev gunlugu senkronu.

URL + anahtar verilirse Supabase REST (`/rest/v1/<table>`) uzerinden INSERT yapar.
Verilmezse `data/task_logs.jsonl` dosyasina yazar. Her iki durumda da hicbir zaman
hata firlatmaz - gunluk kaydi kritik yol degildir.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from config.settings import APP_DIR


class SupabaseSync:
    def __init__(self, url: str = "", key: str = "", table: str = "task_logs") -> None:
        self.url = (url or "").rstrip("/")
        self.key = key or ""
        self.table = table or "task_logs"
        self.enabled = bool(self.url and self.key)
        self._local = APP_DIR / "data" / "task_logs.jsonl"
        self._local.parent.mkdir(parents=True, exist_ok=True)
        if self.enabled:
            logger.info(f"Supabase senkronu aktif: {self.url} / {self.table}")
        else:
            logger.info(f"Supabase anahtari yok -> yerel gunluk: {self._local.name}")

    async def log_task(self, record: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(self._append_local, record)
        except Exception:  # noqa: BLE001
            logger.exception("Yerel gorev gunlugu yazilamadi")
        if not self.enabled:
            return
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{self.url}/rest/v1/{self.table}",
                    headers={
                        "apikey": self.key,
                        "Authorization": f"Bearer {self.key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal",
                    },
                    json=record,
                )
            if resp.status_code >= 300:
                logger.warning(f"Supabase INSERT {resp.status_code}: {resp.text[:160]}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Supabase senkronu basarisiz: {exc!r}")

    def _append_local(self, record: dict[str, Any]) -> None:
        with self._local.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
