"""Claude (Anthropic) istemcisi - yazilim ajanlarinin ana modeli.

agents.json'da modeli "claude-*" olan ajanlar once buradan calisir; hata / bakiye yok /
reddetme durumunda ajan kendi OpenRouter -> Gemini zincirine duser.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import AsyncAnthropic
from loguru import logger

# Kod gorevleri uzun surebilir; SDK 429/5xx'te kendisi 2 kez yeniden dener.
REQUEST_TIMEOUT_S = 300.0
MAX_TOKENS = 16000
# Reddetme (stop_reason="refusal") olursa sunucu istegi uygun modelle yeniden calistirir.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeClient:
    def __init__(self, api_key: str | None = None, workspace_id: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        workspace_id = workspace_id or os.getenv("ANTHROPIC_WORKSPACE_ID")
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY bulunamadi, Claude ajanlari OpenRouter'a duser.")
        self.client = AsyncAnthropic(
            api_key=self.api_key or "dummy-key",
            timeout=REQUEST_TIMEOUT_S,
            default_headers={"anthropic-workspace-id": workspace_id} if workspace_id else None,
        )

    @property
    def available(self) -> bool:
        """Gercek bir API anahtari var mi (yoksa cagri yapmak anlamsiz: 401)."""
        return bool(self.api_key)

    async def create(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,
    ) -> Any:
        """Tek bir Messages API cagrisi; ham yanit (content bloklari + stop_reason) doner."""
        logger.info(f"Claude istegi gonderiliyor -> Model: {model}")
        return await self.client.beta.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=messages,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **({"system": system} if system else {}),
            **({"tools": tools} if tools else {}),
            **({"output_config": {"effort": effort}} if effort else {}),
        )
