"""Telegram kolu - gelen mesajlari dinler, sesli beyne aynalar, izinli sohbetlere otomatik yanit verir.

WhatsApp kolunun (core/whatsapp_handler.py) hafif kardesi:

* **Long-poll.** `getUpdates` (timeout 25 sn) httpx.AsyncClient ile; event loop tikanmaz.
* **Kopru aynasi.** Her gelen mesaj `[TELEGRAM] kisi: metin`, her otomatik yanit
  `[TELEGRAM] (CYRAEN->kisi): metin` olarak `bridge/outbox.txt`'e yazilir -> BrainEngine
  bunlari canli oturuma enjekte eder (sesli bildirim).
* **Otomatik yanit YALNIZCA izinli sohbetlere** (TELEGRAM_ALLOWED_CHAT_IDS; bos ise
  TELEGRAM_DEFAULT_CHAT_ID). Digerleri sadece kopruye bildirilir.
* **Model zinciri.** Once OpenRouter (core.openrouter_client), olmazsa Gemini.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from config.settings import Settings
from core.bridge_mirror import mirror_to_bridge
from core.whatsapp_handler import HONESTY_RULES, ConversationMemory
from tools import telegram_tool as tg

POLL_TIMEOUT_S = 25
REPLY_TIMEOUT_S = 50.0
MAX_BACKOFF_S = 60.0

PERSONA = (
    "Sen CYRAEN'sin - Sezai'nin (DEU BOTE ogrencisi) kisisel yapay zeka asistani. "
    "Telegram'da Sezai adina, onun samimi ve kisa uslubuyla Turkce yaziyorsun. "
    "Mesajlar kisa olsun (1-3 cumle), emoji abartma, resmi dil kullanma."
)


class TelegramHandler:
    def __init__(self, settings: Settings, *, history_size: int = 12) -> None:
        self.settings = settings
        self._memory = ConversationMemory(history_size)
        self._stop = asyncio.Event()
        allowed = settings.telegram_allowed_chat_ids or (
            [settings.telegram_default_chat_id] if settings.telegram_default_chat_id else []
        )
        self.allowed: set[str] = {str(c).strip() for c in allowed if str(c).strip()}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token)

    def request_shutdown(self) -> None:
        self._stop.set()

    async def send_proactive_message(self, chat_id: str | None, text: str) -> bool:
        """Disaridan (zamanlayici, bildirim dagiticisi) cagrilan proaktif gonderim.

        Bot API durumsuz oldugu icin kol calismasa da / baska bir event loop'tan
        cagrilsa da guvenlidir (her cagri kendi HTTP istemcisini acar).
        `chat_id` bos ise TELEGRAM_DEFAULT_CHAT_ID kullanilir. Basariliysa True.
        """
        target = str(chat_id or self.settings.telegram_default_chat_id or "").strip()
        text = (text or "").strip()
        if not (self.enabled and target and text):
            logger.debug("[TG] proaktif mesaj atlandi (token/sohbet/metin yok)")
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    tg.api_url("sendMessage", self.settings.telegram_bot_token),
                    json={"chat_id": target, "text": text[: tg.MAX_TEXT]},
                )
        except httpx.HTTPError as exc:
            logger.warning(f"[TG] proaktif mesaj gonderilemedi: {type(exc).__name__}")
            return False
        if resp.status_code != 200:
            logger.warning(f"[TG] proaktif mesaj reddedildi: HTTP {resp.status_code}")
            return False
        # sohbet gecmisine ekle: kullanici bu mesaja cevap verirse baglam korunur
        self._memory.add(target, "assistant", text)
        return True

    # ------------------------------------------------------------------ yasam dongusu
    async def run(self) -> None:
        """Tum hatalari yutar; beyni asla durdurmaz."""
        if not self.enabled:
            logger.info("[TG] TELEGRAM_BOT_TOKEN yok - Telegram kolu kapali.")
            return
        mode = "otomatik yanit ACIK" if self.settings.telegram_auto_reply else "yalnizca bildirim"
        logger.success(f"[TG] Telegram kolu aktif ({mode}; izinli sohbetler: {len(self.allowed)})")
        backoff = 2.0
        async with httpx.AsyncClient(timeout=POLL_TIMEOUT_S + 10) as client:
            while not self._stop.is_set():
                try:
                    updates = await self._poll(client)
                    backoff = 2.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    # token URL'de -> yalnizca tip adi loglanir
                    logger.warning(f"[TG] yoklama hatasi: {type(exc).__name__}; {backoff:.0f} sn sonra")
                    await self._sleep(backoff)
                    backoff = min(MAX_BACKOFF_S, backoff * 2)
                    continue
                for item in tg.record_updates(updates):
                    try:
                        await self._handle(client, item)
                    except Exception:  # noqa: BLE001
                        logger.exception("[TG] mesaj islenemedi")
        logger.info("[TG] Telegram kolu durdu.")

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def _poll(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        tg.touch_heartbeat()
        offset = int(tg.load_state().get("offset") or 0)
        resp = await client.post(
            tg.api_url("getUpdates"),
            json={"offset": offset, "timeout": POLL_TIMEOUT_S,
                  "allowed_updates": ["message", "edited_message"]},
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(str(data.get("description") or f"HTTP {resp.status_code}")[:120])
        return list(data.get("result") or [])

    # ------------------------------------------------------------------ mesaj isleme
    def should_auto_reply(self, item: dict[str, Any]) -> bool:
        return (
            self.settings.telegram_auto_reply
            and item.get("chat_id") in self.allowed
            and not str(item.get("text", "")).startswith("/")
        )

    async def _handle(self, client: httpx.AsyncClient, item: dict[str, Any]) -> None:
        chat_id, who, text = item["chat_id"], item["sender"], item["text"]
        mirror_to_bridge(f"[TELEGRAM] {who}: {text[:300]}")
        if not self.should_auto_reply(item):
            logger.info(f"[TG] {who} ({chat_id}) mesaji yalnizca bildirildi.")
            return

        history = self._memory.history(chat_id)
        self._memory.add(chat_id, "user", text)
        with contextlib.suppress(Exception):
            await client.post(tg.api_url("sendChatAction"),
                              json={"chat_id": chat_id, "action": "typing"})
        try:
            reply = await asyncio.wait_for(self.generate_reply(history, text), REPLY_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[TG] yanit uretilemedi: {exc!r}")
            return
        reply = (reply or "").strip()
        if not reply:
            return
        resp = await client.post(
            tg.api_url("sendMessage"),
            json={"chat_id": chat_id, "text": reply[: tg.MAX_TEXT]},
        )
        if resp.status_code == 200:
            self._memory.add(chat_id, "assistant", reply)
            mirror_to_bridge(f"[TELEGRAM] (CYRAEN->{who}): {reply[:200]}")
        else:
            logger.warning(f"[TG] yanit gonderilemedi: HTTP {resp.status_code}")

    def _system_prompt(self) -> str:
        now = datetime.now()
        gunler = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
        return "\n\n".join([
            PERSONA, HONESTY_RULES,
            f"Su an: {now:%d.%m.%Y} {gunler[now.weekday()]}, saat {now:%H:%M} (Turkiye).",
            "Internete erisemiyorsun: guncel bilgi gerektiren sorularda tahmin yurutme, "
            "'bakip donerim' de.",
        ])

    async def generate_reply(self, history: list[dict[str, str]], text: str) -> str:
        """Once OpenRouter, sonra Gemini. Ikisi de yoksa istisna."""
        from core.openrouter_client import default_chain, get_openrouter

        system = self._system_prompt()
        router = get_openrouter()
        if router.available:
            messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
            messages += [
                {"role": "assistant" if t["role"] == "assistant" else "user", "content": t["text"]}
                for t in history
            ]
            messages.append({"role": "user", "content": text})
            primary, *fallbacks = default_chain("telegram")
            try:
                msg = await router.chat(messages, model=primary, fallback_models=fallbacks,
                                        temperature=0.7, max_tokens=500)
                if msg.content:
                    return msg.content
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[TG] OpenRouter zinciri basarisiz, Gemini deneniyor: {exc!r}")
        return await self._reply_gemini(system, history, text)

    async def _reply_gemini(self, system: str, history: list[dict[str, str]], text: str) -> str:
        from google import genai
        from google.genai import types

        from agents.genai_util import generate_with_retry

        if not self.settings.gemini_api_key:
            raise RuntimeError("Ne OpenRouter ne Gemini anahtari var")
        client = genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options=types.HttpOptions(api_version=self.settings.agents_api_version,
                                           timeout=60_000),
        )
        contents: list[Any] = [
            types.Content(role="model" if t["role"] == "assistant" else "user",
                          parts=[types.Part(text=t["text"])])
            for t in history
        ]
        contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
        resp = await generate_with_retry(
            client, model=self.settings.agent_model_chain, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.7),
            attempts=2,
        )
        return getattr(resp, "text", "") or ""
