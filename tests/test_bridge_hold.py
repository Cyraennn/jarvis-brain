"""Kopru bekletmesi: telefon/ajan mesaji yanitlanirken ortam sesi modele gitmez."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from core.brain_engine import BrainEngine
from core.events import EngineObserver
from core.wake_word import WakeGate


class Transport:
    """Verilen sayida mikrofon parcasi dondurur, sonra dinleme gorevini bitirir."""

    is_open = True

    def __init__(self, chunks: int, on_chunk=None) -> None:
        self.left = chunks
        self.on_chunk = on_chunk or (lambda i: None)
        self.i = 0

    async def read_chunk(self, _size: int) -> bytes:
        if self.left <= 0:
            raise asyncio.CancelledError
        self.left -= 1
        self.on_chunk(self.i)
        self.i += 1
        return b"\x10\x10" * 8


class Detector:
    def __init__(self, scores=()) -> None:
        self.scores = list(scores)
        self.available = True

    def load(self) -> bool:
        return True

    def score(self, _pcm: bytes) -> float:
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self) -> None:
        pass


def _engine(*, wake: bool = False, hold_s: float = 45.0, scores=()) -> BrainEngine:
    eng = BrainEngine.__new__(BrainEngine)
    eng.settings = SimpleNamespace(
        audio=SimpleNamespace(chunk_size=8, send_sample_rate=16000),
        wake_word_threshold=0.5, bridge_hold_s=hold_s, obsidian_log_conversations=False,
    )
    eng.observer = EngineObserver()
    eng.out_queue = asyncio.Queue(maxsize=200)
    eng._playback_active = asyncio.Event()
    eng._mic_muted = False
    eng._wake_enabled = wake
    eng._wake = Detector(scores)
    eng._gate = WakeGate(window_s=8)
    eng._last_near_miss = float("-inf")
    eng._bridge_hold_until = 0.0
    eng._bridge_skip_turns = 0
    eng._no_followup = False
    eng._turn_tools = False
    eng._user_transcript = ""
    eng._model_transcript = ""
    eng._resume_handle = None
    return eng


def _listen(eng: BrainEngine, chunks: int, on_chunk=None) -> list[str]:
    async def run() -> list[str]:
        eng.audio_transport = Transport(chunks, on_chunk)
        try:
            await eng._listen_audio()
        except asyncio.CancelledError:
            pass
        kinds = []
        while not eng.out_queue.empty():
            kinds.append(eng.out_queue.get_nowait()[0])
        return kinds

    return asyncio.run(run())


def _turn_complete() -> SimpleNamespace:
    return SimpleNamespace(interrupted=None, input_transcription=None,
                           output_transcription=None, turn_complete=True)


def test_mic_flows_normally_without_a_bridge_message():
    assert _listen(_engine(), 3) == ["audio", "audio", "audio"]


def test_hold_blocks_mic_and_ends_the_audio_stream_once():
    eng = _engine()
    eng._hold_for_bridge("[TELEFON] GitHub'da hangi depolarim var?")
    assert eng._bridge_held()
    assert _listen(eng, 4) == ["audio_end"]  # ortam sesi modele gitmedi


def test_reply_turn_complete_releases_the_hold():
    eng = _engine()
    eng._hold_for_bridge("[TELEFON] Saat kac?")
    eng._handle_server_content(_turn_complete())
    assert not eng._bridge_held()
    assert _listen(eng, 2) == ["audio", "audio"]


def test_turn_already_in_progress_does_not_release_the_hold():
    eng = _engine()
    eng._model_transcript = "onceki cevabin ortasi"  # mesaj, model konusurken geldi
    eng._hold_for_bridge("[Entegrasyon Uzmani] sonuc hazir")
    eng._handle_server_content(_turn_complete())  # yarida kalan ONCEKI tur
    assert eng._bridge_held()
    eng._handle_server_content(_turn_complete())  # mesajin kendi yaniti
    assert not eng._bridge_held()


def test_hold_expires_on_its_own():
    eng = _engine()
    eng._hold_for_bridge("[TELEFON] merhaba")
    eng._bridge_hold_until = time.monotonic() - 1  # sure doldu, yanit gelmedi
    assert _listen(eng, 2) == ["audio", "audio"]


def test_hold_can_be_disabled():
    eng = _engine(hold_s=0)
    eng._hold_for_bridge("[TELEFON] merhaba")
    assert not eng._bridge_held() and not eng._gate.awake
    eng._hold_for_bridge("[HATIRLATICI] ilacini ic")
    assert not eng._bridge_held() and eng._gate.awake  # cevap penceresi yine acilir


def test_mid_stream_hold_cuts_audio_from_that_chunk_on():
    eng = _engine()

    def on_chunk(i: int) -> None:
        if i == 2:
            eng._hold_for_bridge("[HATIRLATICI] toplanti")

    assert _listen(eng, 5, on_chunk) == ["audio", "audio", "audio_end"]


def test_wake_word_breaks_the_hold():
    eng = _engine(wake=True, scores=[0.1, 0.9])
    eng._gate.keep_awake()
    eng._hold_for_bridge("[TELEFON] Saat kac?")
    assert not eng._gate.awake  # bekletme kapiyi uyutur
    kinds = _listen(eng, 3)
    assert not eng._bridge_held()  # "Hey CYRAEN" duyuldu
    assert kinds.count("audio") == 3  # on-dolum (2 parca) + uyaniktaki 3. parca


def test_phone_reply_does_not_open_the_mic_window():
    eng = _engine(wake=True)
    eng._hold_for_bridge("[TELEFON] Saat kac?")
    assert eng._no_followup
    eng._handle_server_content(_turn_complete())
    assert not eng._gate.awake  # kullanici PC basinda degil


def test_reminder_reply_opens_the_mic_window():
    eng = _engine(wake=True)
    eng._hold_for_bridge("[HATIRLATICI] ilacini ic")
    assert not eng._no_followup
    eng._handle_server_content(_turn_complete())
    assert eng._gate.awake  # kullanici "tamam" diyebilsin


def test_phone_notification_mirror_is_not_a_remote_conversation():
    eng = _engine()
    eng._hold_for_bridge("[TELEFON BILDIRIMI] WhatsApp: yeni mesaj")
    assert not eng._no_followup


def test_user_speech_clears_the_no_followup_flag():
    eng = _engine()
    eng._hold_for_bridge("[TELEGRAM] Ali: selam")
    eng._handle_server_content(SimpleNamespace(
        interrupted=None, input_transcription=SimpleNamespace(text="Cyraen"),
        output_transcription=None, turn_complete=None))
    assert not eng._no_followup


def test_setup_rejection_disables_proactive_audio_only_right_after_connect():
    eng = _engine()
    eng._proactive_audio = True
    eng._connect_started = time.monotonic() - 60
    eng._check_setup_rejection(RuntimeError("1007 None. Request contains an invalid argument."))
    assert eng._proactive_audio  # oturum ortasindaki 1007 baska bir sorun
    eng._connect_started = time.monotonic()
    eng._check_setup_rejection(RuntimeError("1011 internal"))
    assert eng._proactive_audio
    eng._check_setup_rejection(RuntimeError("1007 None. Request contains an invalid argument."))
    assert not eng._proactive_audio
