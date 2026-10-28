"""OpenRouter Çoklu Model İstemcisi ve Fallback Yönetimi."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from openai import AsyncOpenAI
from loguru import logger

# Model basina ust sinir (sn). SDK kendi icinde yeniden denemez: 429/5xx'te
# beklemek yerine hemen siradaki yedek modele gecilir.
REQUEST_TIMEOUT_S = 30.0

# Kredisiz hesapta tum ucretsiz modeller TEK gunluk kotayi paylasir ("free-models-per-day").
# Kota dolunca gun sonuna (UTC) kadar :free modelleri hic denemeyiz: her cagri 429 yagdirmaz,
# cagiran taraf hemen kendi yedegine (Gemini) gecer. Surec genelinde tek durum (cok istemci var).
_free_quota_until = 0.0


class OpenRouterQuotaError(RuntimeError):
    """Ucretsiz gunluk kota dolu ve denenecek ucretli model yok."""


def _is_free(model: str) -> bool:
    return model.endswith(":free") or model == "openrouter/free"


def _is_daily_quota_error(exc: Exception) -> bool:
    return "429" in str(exc) and "free-models-per-day" in str(exc)


def _next_utc_midnight() -> float:
    now = datetime.now(timezone.utc)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()


def free_quota_exhausted() -> bool:
    return time.time() < _free_quota_until


def quota_status() -> dict[str, Any]:
    """{"exhausted": bool, "until": ISO zaman | None} - durum ekrani ve testler icin."""
    if not free_quota_exhausted():
        return {"exhausted": False, "until": None}
    until = datetime.fromtimestamp(_free_quota_until, timezone.utc).astimezone()
    return {"exhausted": True, "until": until.isoformat(timespec="minutes")}


def _mark_free_quota_exhausted() -> None:
    global _free_quota_until
    if free_quota_exhausted():
        return
    _free_quota_until = _next_utc_midnight()
    until = datetime.fromtimestamp(_free_quota_until, timezone.utc).astimezone()
    logger.warning(
        f"OpenRouter ucretsiz gunluk kota doldu; {until:%H:%M}'e kadar :free modeller atlaniyor "
        "(10$ kredi yuklemek kotayi gunluk 1000 istege cikarir)."
    )


class OpenRouterClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY bulunamadı, varsayılan modeller kullanılabilir.")

        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key or "dummy-key",
            timeout=REQUEST_TIMEOUT_S,
            max_retries=0,
        )

    @property
    def available(self) -> bool:
        """Gercek bir API anahtari var mi (yoksa cagri yapmak anlamsiz: 401)."""
        return bool(self.api_key)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = "openrouter/free",
        fallback_models: list[str] | None = None,
        info: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Ham `message` nesnesini dondurur (tool_calls dahil). Hata -> yedek model.

        `info` verilirse `model` (yanit veren model), `primary` ve `fallback` yazilir.
        Icerik de arac cagrisi da yoksa yanit bos sayilir ve yedege gecilir.
        """
        models_to_try = [model] + (fallback_models or [])
        errors: list[str] = []
        skipped = 0

        for index, current_model in enumerate(models_to_try):
            if _is_free(current_model) and free_quota_exhausted():
                skipped += 1
                errors.append(f"{current_model}: gunluk ucretsiz kota dolu (atlandi)")
                continue
            try:
                logger.info(f"OpenRouter isteği gönderiliyor -> Model: {current_model}")
                response = await self.client.chat.completions.create(
                    model=current_model,
                    messages=messages,
                    extra_headers={
                        "HTTP-Referer": "https://github.com/jarvis-brain",
                        "X-Title": "JARVIS Brain Engine",
                    },
                    **kwargs,
                )
                message = response.choices[0].message if response.choices else None
                if message is not None and (message.content or getattr(message, "tool_calls", None)):
                    if info is not None:
                        info["model"] = getattr(response, "model", None) or current_model
                        info["primary"] = models_to_try[0]
                        info["fallback"] = index > 0
                    return message
                errors.append(f"{current_model}: bos yanit")
                logger.warning(f"Model ({current_model}) boş yanıt döndürdü. Yedek modele geçiliyor...")
            except Exception as exc:
                errors.append(f"{current_model}: {exc!s}"[:200])
                if _is_daily_quota_error(exc):
                    _mark_free_quota_exhausted()
                    continue
                logger.error(f"Model ({current_model}) hatası: {exc!r}. Yedek modele geçiliyor...")

        if info is not None:
            info["errors"] = errors
        if free_quota_exhausted() and all(_is_free(m) for m in models_to_try):
            if skipped == len(models_to_try):
                logger.debug(f"OpenRouter atlandi (kota dolu): {models_to_try[0]}")
            raise OpenRouterQuotaError("OpenRouter ücretsiz günlük kotası dolu.")
        raise RuntimeError("Tüm OpenRouter ve yedek modeller başarısız oldu.")

    async def generate_response(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "openrouter/free",
        fallback_models: list[str] | None = None,
        info: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """OpenRouter üzerinden model çağrısı yapar. Hata durumunda yedek modellere geçer."""
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        message = await self.chat(
            messages, model=model, fallback_models=fallback_models, info=info, **kwargs
        )
        return message.content or ""


# Telegram / Gmail taslakcisi gibi yan kollarin paylastigi varsayilan zincir
DEFAULT_CHAIN: list[str] = [  # yalnizca ucretsiz modeller (hesapta bakiye olmasa da calisir)
    "nvidia/nemotron-3.5-super-vl:free",
    "poolside/laguna-s-2.1:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "dots-studio/dots-3-note-preview:free",
    "cohere/north-mini-code:free",
    "openrouter/free",  # rastgele ucretsiz model -> yalnizca son care
]


@lru_cache(maxsize=1)
def get_openrouter() -> OpenRouterClient:
    """Surec genelinde tek, paylasilan istemci (baglanti havuzu yeniden kullanilir)."""
    return OpenRouterClient()


def _channel_models(channel: str) -> list[str]:
    """agents/agents.json -> "channels": {"<kanal>": {"model": .., "fallback_models": [..]}}."""
    import json
    from pathlib import Path

    try:
        from config.settings import get_settings

        raw = json.loads(Path(get_settings().agent_config_path).read_text(encoding="utf-8"))
        block = (raw.get("channels") or {}).get(channel) or {}
    except Exception:  # noqa: BLE001 - yapilandirma yoksa varsayilan zincir
        return []
    models = [block.get("model"), *(block.get("fallback_models") or [])]
    return [str(m).strip() for m in models if m and "/" in str(m)]


def default_chain(channel: str | None = None) -> list[str]:
    """Yan kollarin model zinciri: kanalin kendi modelleri > OPENROUTER_MODEL > varsayilan.

    Varsayilan zincir her zaman sona eklenir; kanal modeli dusse bile yedek kalir.
    """
    primary = (os.getenv("OPENROUTER_MODEL") or "").strip()
    chain = [*(_channel_models(channel) if channel else []), primary, *DEFAULT_CHAIN]
    seen: set[str] = set()
    return [m for m in chain if m and not (m in seen or seen.add(m))]
