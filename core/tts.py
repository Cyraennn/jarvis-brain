"""Metinden sese (edge-tts, ucretsiz Microsoft noral sesler) - Stark Ekibi sesli yanitlari.

Basarisizlikta None doner; arayuz bu durumda tarayicinin kendi sesine (speechSynthesis) duser.
"""

from __future__ import annotations

import re

from loguru import logger

MAX_CHARS = 1500
ATTEMPTS = 2

_MD = re.compile(r"[*_#`>\[\]]+")
_URL = re.compile(r"https?://\S+")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# emoji ve resim yazilari (ses bunlari adlariyla okumasin)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def speakable(text: str) -> str:
    """Markdown isaretlerini ve linkleri temizler (sesli okunmasinlar)."""
    text = _LINK.sub(r"\1", text or "")
    text = _URL.sub("", text)
    text = _MD.sub("", text)
    text = _EMOJI.sub("", text)
    return " ".join(text.split())[:MAX_CHARS]


async def synthesize(text: str, voice: str, *, rate: str = "+0%", pitch: str = "+0Hz") -> bytes | None:
    """Metni mp3'e cevirir; ses/ag/paket hatasinda None."""
    clean = speakable(text)
    if not clean or not voice:
        return None
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts kurulu degil (pip install edge-tts); tarayici sesine dusulecek")
        return None
    last: Exception | None = None
    for _ in range(ATTEMPTS):   # servis ara sira bos ses / baglanti hatasi donuyor: bir kez daha dene
        try:
            audio = bytearray()
            async for chunk in edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch).stream():
                if chunk.get("type") == "audio":
                    audio += chunk["data"]
            if audio:
                return bytes(audio)
        except Exception as exc:  # noqa: BLE001
            last = exc
    logger.warning(f"TTS basarisiz ({voice}): {last!r}" if last else f"TTS bos ses dondu ({voice})")
    return None
