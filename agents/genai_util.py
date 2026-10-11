"""google-genai `generate_content` icin ortak retry + model-rotasyon sarmalayicisi.

- Dakikalik 429 / gecici 5xx / zaman asimi  -> bekle ve AYNI modelle yeniden dene.
- Gunluk kota (PerDay) 429 / model 404       -> SIRADAKI yedek modele gec.

Yedek modele gecis ASLA sessiz degildir (gozetimsiz sunucu icin kritik):
  - her cagri hangi modelle yapildiysa yapilandirilmis log alani `model` ile loglanir;
  - gecis olursa WARNING + `event=model_fallback` loglanir ve `FALLBACK_HOOKS`'taki
    tum kancalar (orn. sunucunun Telegram bildirimi) cagrilir;
  - cagiran taraf `info` sozlugu verirse `model` / `fallback_from` / `fallback_reasons`
    buraya yazilir; boylece cevaba "yedek model kullanildi" isareti konabilir.

Bulut zincirinin SON modeli de kalici olarak duserse istek yerel modele (Ollama,
`core/local_llm.py`) devredilir - ayni duyuru/isaret mekanizmasiyla. Yerel model kapali,
erisilemez ya da istek desteklenmiyorsa (ses/gorsel) orijinal hata aynen yukselir.
Internet yoksa (`core/connectivity.py`) bulut hic denenmez, dogrudan yerel modele gidilir.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable, Sequence

from google import genai
from google.genai import types
from loguru import logger

_TRANSIENT = ("500", "INTERNAL", "503", "UNAVAILABLE", "504", "DEADLINE_EXCEEDED")
_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")

# Yedek modele gecildiginde cagrilir: hook({"from": .., "to": .., "reason": ..}).
# Kancalar hata firlatirsa yutulur (bildirim hatasi model cagrisini bozmaz).
FALLBACK_HOOKS: list[Callable[[dict[str, Any]], None]] = []


def _retry_delay(message: str) -> float | None:
    m = _RETRY_DELAY_RE.search(message)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _is_transient(text: str) -> bool:
    return any(t in text for t in _TRANSIENT)


def _is_rate_limit(text: str) -> bool:
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def _is_daily_quota(text: str) -> bool:
    low = text.lower()
    return "perday" in low or "per day" in low or "requestsperday" in low


def _is_model_gone(text: str) -> bool:
    return "404" in text and ("NOT_FOUND" in text or "not found" in text or "no longer available" in text)


def _announce_fallback(current: str, nxt: str, reason: str, info: dict[str, Any] | None) -> None:
    event = {"from": current, "to": nxt, "reason": reason[:200]}
    logger.bind(event="model_fallback", model=current, fallback_to=nxt).warning(
        f"YEDEK MODELE GECILIYOR: '{current}' kullanilamadi ({reason[:90]}) -> '{nxt}'"
    )
    if info is not None:
        info.setdefault("fallback_from", []).append(current)
        info.setdefault("fallback_reasons", []).append(reason[:200])
    for hook in list(FALLBACK_HOOKS):
        try:
            hook(event)
        except Exception:  # noqa: BLE001 - bildirim hatasi cagriyi bozmaz
            logger.exception("fallback kancasi hata verdi")


def _get_local() -> Any:
    """Yerel model istemcisi ya da None (testler bunu degistirir)."""
    from core.local_llm import get_local_llm

    return get_local_llm()


async def _is_online() -> bool:
    from core.connectivity import is_online

    return await is_online()


async def _try_local(
    current: str, reason: str, contents: Any, config: Any, primary: str,
    info: dict[str, Any] | None,
) -> Any:
    """Bulut zinciri bitti: yerel modeli dene. Basarisizsa None (cagiran orijinali yukseltir)."""
    from core.local_llm import LocalLLMError, model_label, supports

    local = _get_local()
    if local is None or not supports(contents) or not await local.is_up():
        return None
    started = time.monotonic()
    try:
        response, used = await local.generate(contents, config)
    except LocalLLMError as exc:
        logger.bind(event="model_call", model="ollama", ok=False).warning(str(exc)[:200])
        if info is not None:
            info["local_error"] = str(exc)[:200]
        return None
    label = model_label(used)
    _announce_fallback(current, label, reason, info)
    elapsed = int((time.monotonic() - started) * 1000)
    logger.bind(
        event="model_call", model=label, ok=True, latency_ms=elapsed,
        fallback=True, primary=primary,
    ).info(f"Model cagrisi: {label} ({elapsed} ms) [YEREL YEDEK - asil model: {primary}]")
    if info is not None:
        info["model"] = label
        info["primary"] = primary
        info["fallback"] = True
    return response


async def generate_with_retry(
    client: genai.Client,
    *,
    model: str | Sequence[str],
    contents: Any,
    config: types.GenerateContentConfig | None = None,
    attempts: int = 3,
    base_delay: float = 6.0,
    max_delay: float = 45.0,
    timeout: float = 60.0,
    info: dict[str, Any] | None = None,
) -> Any:
    models = [model] if isinstance(model, str) else list(model)
    if not models:
        raise ValueError("En az bir model gerekli")

    # Cevrimdisi: bulutu hic deneme (her model icin baglanti hatasi beklemek ~45 sn surer)
    if _get_local() is not None and not await _is_online():
        local = await _try_local(models[0], "internet yok", contents, config, models[0], info)
        if local is not None:
            return local
        raise ConnectionError("Internet baglantisi yok ve yerel model yanit vermedi")

    last: BaseException | None = None
    for m_index, current in enumerate(models):
        is_last_model = m_index == len(models) - 1
        nxt = models[m_index + 1] if not is_last_model else ""
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=current, contents=contents, config=config
                    ),
                    timeout=timeout,
                )
                elapsed = int((time.monotonic() - started) * 1000)
                fell_back = m_index > 0
                logger.bind(
                    event="model_call", model=current, ok=True, latency_ms=elapsed,
                    fallback=fell_back, primary=models[0],
                ).info(
                    f"Model cagrisi: {current} ({elapsed} ms)"
                    + (f" [YEDEK - asil model: {models[0]}]" if fell_back else "")
                )
                if info is not None:
                    info["model"] = current
                    info["primary"] = models[0]
                    info["fallback"] = fell_back
                return response
            except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
                last = exc
                text = "" if isinstance(exc, asyncio.TimeoutError) else str(exc)
                timed_out = isinstance(exc, asyncio.TimeoutError)
                logger.bind(event="model_call", model=current, ok=False).debug(
                    f"Model cagrisi basarisiz: {current}: {(text or 'zaman asimi')[:120]}"
                )

                # kalici -> yedek modele gec
                if _is_model_gone(text) or (_is_rate_limit(text) and _is_daily_quota(text)):
                    if is_last_model:
                        local = await _try_local(current, text, contents, config, models[0], info)
                        if local is not None:
                            return local
                        raise
                    _announce_fallback(current, nxt, text, info)
                    break

                # gecici -> bekle, ayni modelle yeniden dene
                if (timed_out or _is_transient(text) or _is_rate_limit(text)) and attempt < attempts:
                    delay = _retry_delay(text) or min(max_delay, base_delay * (2 ** (attempt - 1)))
                    reason = "zaman asimi" if timed_out else text[:110]
                    logger.warning(
                        f"[{current}] gecici hata (deneme {attempt}/{attempts}), "
                        f"{delay:.0f}s: {reason}"
                    )
                    await asyncio.sleep(delay)
                    continue

                # son deneme / kalici hata
                if is_last_model:
                    local = await _try_local(
                        current, text or "zaman asimi", contents, config, models[0], info
                    )
                    if local is not None:
                        return local
                    raise
                _announce_fallback(current, nxt, text or "zaman asimi", info)
                break

    assert last is not None
    raise last


def fallback_note(info: dict[str, Any]) -> str:
    """Cevaba eklenecek acik isaret; yedek kullanilmadiysa bos."""
    if not info.get("fallback"):
        return ""
    return (
        f"[YEDEK MODEL: {info.get('model')} kullanildi - asil model "
        f"{info.get('primary')} yanit vermedi] "
    )


async def quick_text(
    settings: Any, system: str, prompt: str, *, temperature: float = 0.5, attempts: int = 2
) -> tuple[str, str]:
    """Tek seferlik metin uretimi (ajan model zinciri -> yerel model). (metin, model) doner;
    anahtar yoksa ya da zincirin tamami duserse ("", "") - cagiran sablona duser."""
    if not settings.gemini_api_key:
        return "", ""
    info: dict[str, Any] = {}
    try:
        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(api_version=settings.agents_api_version),
        )
        resp = await generate_with_retry(
            client, model=settings.agent_model_chain, contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature),
            attempts=attempts, info=info,
        )
        return (getattr(resp, "text", "") or "").strip(), str(info.get("model") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Metin uretimi basarisiz: {exc!r}")
        return "", ""
