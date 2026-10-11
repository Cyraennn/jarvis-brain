"""Acilista (ve /health?probe=1 ile) TUM modellerin gercekten erisilebilir oldugunu test eder.

Her model icin GERCEK kucuk bir istek atilir:
  - canli ses modeli  : Live oturumu acilir, "ping" gonderilir, ilk yanit beklenir
  - ajan model zinciri: her model icin generate_content("ping")
  - GBrain embedding  : embed_content("ping")

Basarisiz model otomatik olarak "atlanmaz"; sonuc loglanir (event=model_probe), /health'te
gorunur ve Telegram'a bildirilir. Ajanlarin birincil modeli calismiyorsa, hangi YEDEK modelle
calisacaklari ACIKCA bildirilir.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from google import genai
from google.genai import types
from loguru import logger

from config.settings import Settings

LIVE_TIMEOUT_S = 25.0
GEN_TIMEOUT_S = 30.0


@dataclass
class ModelStatus:
    name: str
    role: str            # "live" | "agent" | "embedding"
    ok: bool
    latency_ms: int = 0
    error: str = ""
    checked_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _short(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text.replace("\n", " ")[:220]


async def _timed(role: str, name: str, coro_factory: Callable[[], Any], timeout: float) -> ModelStatus:
    started = time.monotonic()
    try:
        await asyncio.wait_for(coro_factory(), timeout=timeout)
        ok, err = True, ""
    except asyncio.TimeoutError:
        ok, err = False, f"{timeout:.0f} sn zaman asimi"
    except Exception as exc:  # noqa: BLE001
        ok, err = False, _short(exc)
    status = ModelStatus(name=name, role=role, ok=ok, error=err, checked_at=time.time(),
                         latency_ms=int((time.monotonic() - started) * 1000))
    log = logger.bind(event="model_probe", model=name, role=role, ok=ok, latency_ms=status.latency_ms)
    if ok:
        log.info(f"Model testi OK: {name} ({role}, {status.latency_ms} ms)")
    else:
        log.error(f"Model testi BASARISIZ: {name} ({role}): {err}")
    return status


async def _probe_live(client: genai.Client, model: str) -> None:
    config = types.LiveConnectConfig(response_modalities=["AUDIO"])
    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text="ping")]), turn_complete=True
        )
        async for _ in session.receive():
            return  # ilk yanit yeterli


async def _probe_generate(client: genai.Client, model: str) -> None:
    resp = await client.aio.models.generate_content(
        model=model, contents="ping - yalnizca 'ok' yaz",
        config=types.GenerateContentConfig(max_output_tokens=32, temperature=0.0),
    )
    if resp is None:
        raise RuntimeError("bos yanit")


async def _probe_embed(client: genai.Client, model: str) -> None:
    await client.aio.models.embed_content(model=model, contents="ping")


async def probe_models(settings: Settings) -> list[ModelStatus]:
    live_client = genai.Client(api_key=settings.gemini_api_key,
                               http_options=types.HttpOptions(api_version=settings.api_version))
    agent_client = genai.Client(api_key=settings.gemini_api_key,
                                http_options=types.HttpOptions(api_version=settings.agents_api_version))
    checks = [_timed("live", settings.model, lambda: _probe_live(live_client, settings.model),
                     LIVE_TIMEOUT_S)]
    checks += [
        _timed("agent", m, (lambda m=m: _probe_generate(agent_client, m)), GEN_TIMEOUT_S)
        for m in settings.agent_model_chain
    ]
    if getattr(settings, "gbrain_enabled", False):
        checks.append(_timed("embedding", settings.gbrain_embed_model,
                             lambda: _probe_embed(agent_client, settings.gbrain_embed_model),
                             GEN_TIMEOUT_S))
    return list(await asyncio.gather(*checks))


def summarize(results: list[ModelStatus], agent_chain: list[str]) -> list[str]:
    """Kullaniciya bildirilecek sorun cumleleri (bossa her sey yolunda)."""
    problems: list[str] = []
    by_name = {(r.role, r.name): r for r in results}
    for r in results:
        if r.role == "live" and not r.ok:
            problems.append(f"CANLI SES MODELI CALISMIYOR: {r.name} - {r.error}. JARVIS sesli yanit veremez.")
        if r.role == "embedding" and not r.ok:
            problems.append(f"GBrain embedding modeli calismiyor: {r.name} - {r.error} "
                            "(kelime aramasi yedegi kullanilacak).")
    agent_ok = [m for m in agent_chain if by_name.get(("agent", m)) and by_name[("agent", m)].ok]
    if agent_chain and agent_chain[0] not in agent_ok:
        primary = by_name.get(("agent", agent_chain[0]))
        why = primary.error if primary else "test edilmedi"
        if agent_ok:
            problems.append(f"Ajanlarin birincil modeli {agent_chain[0]} calismiyor ({why}). "
                            f"Ajanlar YEDEK model {agent_ok[0]} ile calisacak ve cevaplar isaretlenecek.")
        else:
            problems.append(f"Ajan model zincirinin HICBIR modeli calismiyor ({', '.join(agent_chain)}). "
                            "Ajan gorevleri basarisiz olacak.")
    return problems
