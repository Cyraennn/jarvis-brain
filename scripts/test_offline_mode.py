"""Dogrulama betigi: internet yokken JARVIS yerel modelle hizli ve aracli calisiyor mu?

Calistir:  python scripts/test_offline_mode.py   (Ollama acik olmali; internet KESILMEZ,
yoklama "cevrimdisi" donecek sekilde zorlanir)

  (a) generate_with_retry bulutu hic denemeden yerel modele gider (eskiden ~46 sn).
  (b) Cevrimdisi yazili sohbet gercek araclari (salt okunur) cagirir.
  (c) Cevrimdisi SESLI sohbet: sentezlenmis bir soru (mikrofon yerine) -> vosk -> yerel
      model -> yerel TTS. Hoparlorden ses CALINMAZ; uretilen PCM sayilir.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google import genai  # noqa: E402
from loguru import logger  # noqa: E402

from agents import genai_util  # noqa: E402
from config.settings import get_settings  # noqa: E402
from core.local_llm import get_local_llm  # noqa: E402
from core.offline_chat import OfflineChat  # noqa: E402
from core.offline_voice import build_offline_voice, resample_int16  # noqa: E402
from tools.tool_runner import ToolRunner  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


async def _offline() -> bool:
    return False


class _ScriptedAudio:
    """Mikrofon yerine hazir PCM verir, hoparlor yerine yazilani toplar."""

    is_open = True

    def __init__(self, question_pcm: bytes, chunk_bytes: int) -> None:
        self._pcm, self._step, self._pos = question_pcm, chunk_bytes, 0
        self.spoken = bytearray()

    def open(self, *a, **k) -> None: ...
    def close(self) -> None: ...
    def shutdown(self) -> None: ...

    async def read_chunk(self, _size: int) -> bytes:
        chunk = self._pcm[self._pos:self._pos + self._step]
        self._pos += self._step
        if len(chunk) < self._step:  # soru bitti: sessizlik (gercek zamanli hizda)
            await asyncio.sleep(0.02)
            return b"\0" * self._step
        await asyncio.sleep(0)
        return chunk

    async def write_chunk(self, data: bytes) -> None:
        self.spoken += data


async def _voice_round_trip(settings, chat: OfflineChat) -> bool:
    from core.brain_engine import BrainEngine

    voice = build_offline_voice(settings)
    if not voice.load():
        print(f"{FAIL} yerel STT/TTS yuklenemedi")
        return False
    audio = settings.audio
    question = "Saat kaç?"
    pcm = resample_int16(voice.tts.synthesize(question), audio.receive_sample_rate,
                         audio.send_sample_rate)
    transport = _ScriptedAudio(pcm, audio.chunk_size * audio.sample_width)
    engine = BrainEngine(settings, audio_transport=transport)
    engine._wake_enabled = False  # sentez ses "Hey JARVIS" demiyor
    engine._offline_chat, engine._offline_voice_io = chat, voice
    heard: list[str] = []
    engine.observer.on_user_transcript = lambda text, final: heard.append(text)
    started = time.monotonic()
    engine._start_offline_voice()
    try:
        while time.monotonic() - started < 90:
            await asyncio.sleep(0.2)
            if transport.spoken and not engine._playback_active.is_set():
                break
    finally:
        await engine._stop_offline_voice()
    seconds = len(transport.spoken) / (audio.receive_sample_rate * audio.sample_width)
    print(f"\n(c) soylenen '{question}' -> duyulan {heard} -> {seconds:.1f} sn sesli yanit "
          f"({voice.tts.active}, {time.monotonic() - started:.1f} sn)")
    return bool(heard) and "saat" in heard[0] and seconds > 0.5


async def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")
    local = get_local_llm()
    if local is None or not await local.is_up():
        print(f"{FAIL} Yerel model kapali/erisilemiyor")
        return 1
    genai_util._is_online = _offline  # internet yok taklidi
    ok = True

    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key or "yok")
    started = time.monotonic()
    info: dict = {}
    resp = await genai_util.generate_with_retry(
        client, model=settings.agent_model_chain, contents="Tek cumleyle selam ver.", info=info
    )
    took = time.monotonic() - started
    print(f"\n(a) {took:.1f} sn, model={info.get('model')}: {resp.text}")
    good = str(info.get("model")).startswith("ollama/") and took < 20
    ok &= good
    print(f"{PASS if good else FAIL} bulut atlandi, yerel yanit hizli geldi")

    tools: list[str] = []
    chat = OfflineChat(ToolRunner(), local,
                       notify=lambda *a: a[0] == "on_tool_call" and tools.extend(a[1]))
    for question, expect in (("Saat kac?", "get_current_datetime"),
                             ("Bu hafta sinavim var mi?", "okul_")):
        started = time.monotonic()
        answer = await chat.reply(question)
        print(f"\n(b) '{question}' ({time.monotonic() - started:.1f} sn) araclar={tools}\n{answer}")
        good = any(t.startswith(expect) for t in tools)
        ok &= good
        print(f"{PASS if good else FAIL} '{expect}' araci cagrildi")
        tools.clear()

    good = await _voice_round_trip(settings, chat)
    ok &= good
    print(f"{PASS if good else FAIL} sesli soru anlasildi ve sesli yanitlandi")

    print("\nSONUC:", "TAMAM" if ok else "BASARISIZ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
