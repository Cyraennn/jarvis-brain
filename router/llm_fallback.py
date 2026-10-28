"""Guven esigin altindaysa en hizli kucuk modele tek bir JSON yonlendirme sorusu."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

AskFn = Callable[[str], Awaitable[str]]

_PROMPT = (
    "Bir kisisel asistana gelen istegi siniflandir. YALNIZCA su JSON'u dondur:\n"
    '{{"task_type": "<{types}>", "difficulty": "<basit|orta|zor>"}}\n'
    "basit: tek adim, kisa cevap. orta: birkac adim/ozet. zor: kapsamli arastirma, "
    "cok adimli kod/mimari, uzun rapor.\n\nISTEK:\n{text}"
)


@dataclass
class LlmVerdict:
    task_type: str
    difficulty: str
    raw: str


class LlmRouter:
    def __init__(self, ask: AskFn, *, task_types: list[str], timeout_s: float = 6.0) -> None:
        self.ask = ask
        self.task_types = [t for t in task_types if t != "qa"]
        self.timeout_s = timeout_s

    async def classify(self, text: str) -> LlmVerdict:
        prompt = _PROMPT.format(types="|".join(self.task_types), text=(text or "")[:2000])
        raw = await asyncio.wait_for(self.ask(prompt), timeout=self.timeout_s)
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not match:
            raise ValueError(f"JSON yok: {raw[:120]!r}")
        data = json.loads(match.group(0))
        task_type = str(data.get("task_type", "")).strip().lower()
        difficulty = str(data.get("difficulty", "")).strip().lower()
        if task_type not in self.task_types or difficulty not in ("basit", "orta", "zor"):
            raise ValueError(f"gecersiz etiket: {data}")
        return LlmVerdict(task_type, difficulty, raw[:200])
