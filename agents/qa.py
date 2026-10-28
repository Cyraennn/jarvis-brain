"""V.E.R.O.N.I.C.A. kalite kontrolu (QA): "zor" gorevlerde ajan sonucu kullaniciya gitmeden
denetlenir.

Model router'in `qa` kuralindan gelir (her zaman en guclu model: claude-opus-5-5; hiz icin
kaliteden odun verilmez). Claude dusurse zincirdeki yedege ACIK gecilir (WARNING). Hicbir
model yanit vermezse sonuc "QA yapilamadi" notuyla iletilir - sessizce onaylanmis sayilmaz.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from agents.agent import is_claude_model, is_openrouter_model

_SYSTEM = (
    "Sen V.E.R.O.N.I.C.A.'sin: JARVIS ekibinin kalite kontrol uzmanisin. Bir alt ajanin "
    "kullaniciya (Sezai) gondermek uzere hazirladigi sonucu denetlersin. Olcutler: gorevi "
    "eksiksiz karsiliyor mu, olgusal/teknik hata var mi, uydurma (kaynaksiz tarih, sayi, "
    "dosya, komut) var mi, Turkce ve anlasilir mi. Kucuk uslup kusurlari icin reddetme.\n"
    "YALNIZCA su JSON'u dondur:\n"
    '{"onay": true|false, "sorunlar": ["<kisa madde>", ...], "ozet": "<tek cumle>"}'
)


@dataclass
class QaVerdict:
    approved: bool | None          # None: QA yapilamadi (hicbir model yanit vermedi)
    issues: list[str] = field(default_factory=list)
    summary: str = ""
    model: str | None = None
    fallback: bool = False
    errors: list[str] = field(default_factory=list)


def parse_verdict(text: str) -> tuple[bool, list[str], str]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError(f"QA yaniti JSON degil: {(text or '')[:120]!r}")
    data = json.loads(match.group(0))
    approved = data.get("onay")
    if not isinstance(approved, bool):
        raise ValueError(f"QA yanitinda 'onay' yok: {data}")
    issues = [str(x)[:300] for x in (data.get("sorunlar") or []) if str(x).strip()]
    return approved, issues[:8], str(data.get("ozet", ""))[:300]


class VeronicaQA:
    def __init__(self, *, claude: Any | None, openrouter: Any | None, genai_client: Any | None,
                 max_result_chars: int = 6000) -> None:
        self.claude = claude
        self.openrouter = openrouter
        self.genai_client = genai_client
        self.max_result_chars = max_result_chars

    def _prompt(self, task: str, result: str) -> str:
        return (f"=== GOREV ===\n{task[:3000]}\n\n=== AJAN SONUCU ===\n"
                f"{result[: self.max_result_chars]}\n\nDenetle ve JSON'u dondur.")

    async def _ask(self, model: str, prompt: str) -> str:
        if is_claude_model(model):
            if not getattr(self.claude, "available", False):
                raise RuntimeError("ANTHROPIC_API_KEY yok")
            resp = await self.claude.create([{"role": "user", "content": prompt}], model=model,
                                            system=_SYSTEM, effort="medium")
            if getattr(resp, "stop_reason", None) == "refusal":
                raise RuntimeError("Claude istegi reddetti")
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if is_openrouter_model(model):
            if not getattr(self.openrouter, "available", False):
                raise RuntimeError("OPENROUTER_API_KEY yok")
            return await self.openrouter.generate_response(
                prompt, model=model, fallback_models=[], system_prompt=_SYSTEM, temperature=0.0)
        if self.genai_client is None:
            raise RuntimeError("Gemini istemcisi yok")
        from google.genai import types

        from agents.genai_util import generate_with_retry

        resp = await generate_with_retry(
            self.genai_client, model=[model], contents=prompt, attempts=1,
            config=types.GenerateContentConfig(system_instruction=_SYSTEM, temperature=0.0,
                                               response_mime_type="application/json"),
        )
        return getattr(resp, "text", "") or ""

    async def review(self, task: str, result: str, chain: list[str], *, request_id: str = "") -> QaVerdict:
        prompt = self._prompt(task, result)
        errors: list[str] = []
        for index, model in enumerate(chain):
            try:
                text = await self._ask(model, prompt)
                approved, issues, summary = parse_verdict(text)
            except Exception as exc:  # noqa: BLE001 - siradaki modele ACIK gecis
                errors.append(f"{model}: {type(exc).__name__}: {str(exc)[:160]}")
                nxt = chain[index + 1] if index + 1 < len(chain) else None
                logger.bind(event="qa_fallback").warning(
                    f"[QA {request_id}] {model} denetleyemedi ({errors[-1]})"
                    + (f" -> YEDEK {nxt}" if nxt else " -> QA YAPILAMADI")
                )
                continue
            verdict = QaVerdict(approved, issues, summary, model=model, fallback=index > 0, errors=errors)
            logger.info(f"[QA {request_id}] {model}: {'ONAY' if approved else 'RED'}"
                        + (f" ({'; '.join(issues[:3])})" if issues else ""))
            return verdict
        return QaVerdict(None, errors=errors)
