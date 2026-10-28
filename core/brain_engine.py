"""CANLI BEYIN MOTORU (BrainEngine).

Gemini Live WebSocket API (google-genai / v1alpha) uzerinden tek bir
`asyncio.TaskGroup` icinde 7 paralel gorevi yonetir:

    1. _send_realtime        : out_queue -> canli oturum (mikrofon + webcam + ekran paketleri)
    2. _listen_audio         : PyAudio 16 kHz PCM yakalama (model konusurken eko engelleme)
    3. _receive_audio        : model yanitlari + transkriptler + tool_call istekleri
    4. _play_audio           : 24 kHz PCM yaniti hoparlorden calma
    5. _stream_webcam_frames : ~1.5 sn'de bir en guncel webcam JPEG karesi
    6. _stream_screen_frames : ~2 sn'de bir en guncel ekran goruntusu (mss)
    7. _watch_bridge_inbox   : bridge/outbox.txt -> send_client_content enjeksiyonu

Baglanti koparsa exponential-backoff ile otomatik yeniden baglanir.

Opsiyonel bir `EngineObserver` verilirse (arayuz katmani icin) tum onemli olaylar
yayinlanir. Gozlemci cagrilari motor thread'inden gelir ve hatalari yutulur.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import random
import re
import time
from typing import Any, Callable

import numpy as np
from google import genai
from google.genai import types
from loguru import logger

from config.settings import Settings
from core import personas, voice_fx
from core.async_worker import get_worker
from core.audio_transport import AudioTransport, LocalAudioTransport
from core.bridge_listener import BridgeListener
from core.events import EngineObserver
from core.screen_streamer import ScreenStreamer
from core.wake_word import WakeGate, WakeWordDetector
from core.webcam_streamer import WebcamStreamer
from tools.adb_tool import get_adb_controller
from tools.tool_declarations import get_tools
from tools.tool_runner import ToolRunner

# out_queue eleman tipi: ("audio" | "video", types.Blob)
QueueItem = tuple[str, types.Blob]

# int16 PCM icin tam-olcek normalizasyon referansi (~ -12 dBFS civari doygunluk)
_PCM_FULL_SCALE = 9000.0
# Uyandirma penceresini uzatan konusma seviyesi (_rms_level olceginde; ortam gurultusu < ~0.02)
_WAKE_SPEECH_LEVEL = 0.05
_WAKE_NEAR_MISS = 0.3       # esigin altindaki bu skorlar esik ayari icin loglanir
_WAKE_NEAR_MISS_EVERY_S = 5.0


def _rms_level(pcm: bytes) -> float:
    """int16 PCM tamponunun 0.0 - 1.0 arasi normalize RMS seviyesi."""
    if not pcm:
        return 0.0
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
    return max(0.0, min(1.0, rms / _PCM_FULL_SCALE))


# PortAudio hata kodlari -10000..-9972 (or. -9999 'Unanticipated host error',
# -9988 'Stream closed'); PyAudio bunlari OSError(errno, msg) olarak firlatir.
def _is_audio_error(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and isinstance(exc.errno, int) and -10000 <= exc.errno <= -9972


class _PersonaSwitch(Exception):
    """Kisilik degisti: oturum kapatilir, yeni prompt + sesle hemen yeniden baglanilir."""


# Kullanicinin PC basinda olmadigi kopru kaynaklari: yanit sonrasi mikrofon penceresi acilmaz.
_REMOTE_SOURCES = ("[TELEFON]", "[TELEGRAM]", "[WHATSAPP]")
# El Kontrolu jest komutlari (web /el): kullanici PC basinda, mikrofon bekletilmez.
_GESTURE_SOURCE = "[EL]"
# Baglantidan sonra bu kadar surede gelen 1007, kurulum (config) reddi sayilir.
_SETUP_REJECT_S = 10.0
# Devam tutamagi, oturum kapandiktan sonra sunucuda sinirli sure gecerlidir.
_RESUME_TTL_S = 100 * 60.0
# Oturum en az bu kadar ayakta kaldiysa kopus yeni bir sorun sayilir: geri cekilme bastan baslar.
_STABLE_SESSION_S = 60.0
_OFFLINE_TTS_STEP_S = 0.1
# Konusmaci dogrulama: uyanista bakilan ses, pencere acikken degerlendirilen dilim uzunlugu
_SPEAKER_WAKE_S = 1.5
_SPEAKER_SEGMENT_S = 2.0
_SPEAKER_WAKE_MARGIN = 0.05  # kisa "Hey JARVIS" uzun cumleden daha dusuk skor verir

# Native-audio modeli bazen transkripte ham kontrol tokenlari sizdirir ('<ctrl46>').
_CTRL_TOKEN_RE = re.compile(r"<ctrl\d+>")


class BrainEngine:
    # Konusmaci dogrulama ("yalniz benim sesim"); `_init_speaker_verify` kurar, kapaliysa None
    _speaker: Any = None
    _speaker_gate: Any = None
    _speaker_task: "asyncio.Task[None] | None" = None
    # Kisilik modu; __init__ data/persona.json'dan kurar (None = varsayilan JARVIS)
    _persona: "personas.PersonaMode | None" = None
    _fx: Any = None  # ses efekti islemcisi (ULTRON), efektsizse None

    def __init__(
        self,
        settings: Settings,
        observer: EngineObserver | None = None,
        webcam: WebcamStreamer | None = None,
        bridge: BridgeListener | None = None,
        screen: "ScreenStreamer | None" = None,
        audio_transport: AudioTransport | None = None,
    ) -> None:
        self.settings = settings
        self.observer = observer or EngineObserver()

        self.audio_transport = audio_transport or LocalAudioTransport(settings)
        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(api_version=settings.api_version),
        )

        self.tool_runner = ToolRunner(
            confirm=self._confirm,
            on_exit=self._request_exit,
            on_typing=lambda active: self._notify("on_external_typing", active),
            on_look_at_screen=lambda: self.set_screen_streaming(True),
            on_panel=self._show_panel,
            disabled_groups=set(getattr(settings, "tool_groups_disabled", ())),
        )

        # Android ADB Control (Ultron): bagli telefonlari yonetir. Surec genelinde
        # tek ornek; agir is yok, asenkron kesif run() basinda `_probe_adb` ile yapilir.
        self.adb = get_adb_controller(settings)

        # webcam / bridge disaridan verilmezse motor sahiplenir (headless mod).
        self._owns_webcam = webcam is None
        self.webcam = webcam or WebcamStreamer(
            index=settings.webcam_index,
            jpeg_quality=settings.webcam_jpeg_quality,
        )
        self.bridge = bridge or BridgeListener(
            path=settings.bridge_outbox_path,
            poll_interval=settings.bridge_poll_interval,
        )

        self._owns_screen = screen is None
        self.screen = screen or ScreenStreamer(
            monitor=settings.screen_monitor,
            jpeg_quality=settings.screen_jpeg_quality,
            interval=settings.screen_interval,
        )

        self.session: Any = None  # types.AsyncSession
        # canli oturum yokken yazili sohbeti yerel modelle yanitlar (ilk kullanimda kurulur)
        self._offline_chat: Any = None
        # internet yokken sesli sohbet (vosk + yerel TTS); ilk cevrimdisi donemde yuklenir
        self._offline_voice_io: Any = None
        self._offline_voice_task: asyncio.Task[None] | None = None
        self._offline_listening = False  # yerel STT/TTS yuklendi, mikrofon dinleniyor
        self._local_warmed = False  # bu cevrimdisi donemde yerel model on-yuklendi mi
        self.out_queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=200)
        self.audio_in_queue: asyncio.Queue[bytes] = asyncio.Queue()

        self._audio_ok = True

        # Model konusurken set edilir => mikrofon paketleri gonderilmez (eko engelleme)
        self._playback_active = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._speaking = False

        # Calisma zamani anahtarlari (arayuzden degistirilebilir)
        self._mic_muted = False
        self._output_muted = False  # "uzak mod": PC hoparloru sustur (telefon TTS devrede)
        self._webcam_streaming = settings.webcam_enabled
        self._screen_streaming = settings.screen_enabled

        # Uyandirma kelimesi kapisi ("Hey JARVIS"); detektor ilk ihtiyacta yuklenir
        self._wake_enabled = bool(settings.wake_word_enabled)
        self._last_near_miss = float("-inf")
        self._wake = WakeWordDetector(settings.wake_word_model)
        self._gate = WakeGate(
            window_s=settings.wake_window_s, max_awake_s=settings.wake_max_awake_s
        )

        # profil varsa uyandirma kapisi yalniz kayitli sese acilir
        self._recent_pcm: collections.deque[bytes] = collections.deque(maxlen=1)
        self._init_speaker_verify()

        # Kopru mesaji yanitlanirken mikrofon modele kapali (bkz. _hold_for_bridge)
        self._bridge_hold_until = 0.0
        self._bridge_skip_turns = 0
        self._no_followup = False
        self._turn_tools = False  # acik turda arac cagrildi mi (tur suruyor demek)
        # interrupt_speaking(): tur bitene kadar gelen ses atilir (yoksa model akisi surer)
        self._discard_audio = False
        self._offline_stop = False

        self._proactive_audio = bool(settings.proactive_audio)
        self._connect_started = 0.0

        # Oturum devam ettirme: baglanti kopunca konusma kaldigi yerden surer. Tutamak yalniz
        # bellekte durur (uygulamayi yeniden baslatmak temiz oturum acar).
        self._resume_handle: str | None = None
        self._resume_saved_at = 0.0
        self._resume_failures = 0
        self._attempt_active = False  # bu baglanti denemesinde oturum kuruldu mu

        self._user_transcript = ""
        self._model_transcript = ""

        # Kisilik modu (JARVIS / FRIDAY / ULTRON): prompt + ses baglanti aninda uygulanir
        self._persona = personas.load_active(settings)
        self._persona_switch = asyncio.Event()
        self._fx = voice_fx.make(
            self._persona.audio_effect, settings.audio.receive_sample_rate
        )

    # ============================================================ dis kontrol

    @property
    def persona(self) -> str:
        return self._persona.key if self._persona else personas.DEFAULT_KEY

    def set_persona(self, key: str) -> None:
        """Kisiligi degistirir. Prompt ve ses yalniz baglanirken uygulandigi icin acik
        oturum kapatilir; devam tutamagi da birakilir, yoksa eski kisilik surer."""
        mode = personas.get(self.settings, key)
        if mode.key == self.persona:
            return
        self._persona = mode
        self._fx = voice_fx.make(mode.audio_effect, self.settings.audio.receive_sample_rate)
        personas.save_active(self.settings, mode.key)
        self._drop_resume_handle("kisilik degisti")
        logger.info(f"Kisilik degisti: {mode.name} (ses {mode.voice_name}).")
        self._notify("on_persona", mode.key)
        if self.session is not None:
            self._persona_switch.set()

    async def _watch_persona_switch(self) -> None:
        await self._persona_switch.wait()
        self._persona_switch.clear()
        raise _PersonaSwitch()

    def request_shutdown(self) -> None:
        """Sinyal isleyicilerinden / arayuzden guvenli kapatma tetikler."""
        logger.info("Kapatma istegi alindi.")
        self._shutdown.set()

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = bool(muted)
        logger.info(f"Mikrofon {'sessize alindi' if muted else 'acildi'}.")

    def set_wake_word_enabled(self, enabled: bool) -> None:
        """Uyandirma kelimesi kapisini ac/kapat. Kapaliyken mikrofon her zaman dinler."""
        self._wake_enabled = bool(enabled)
        self._gate.sleep()
        self._gate.transition()  # durum raporunu sifirla (uykuda basla)
        self._notify("on_wake", not self._wake_enabled)
        logger.info(f"Uyandirma kelimesi {'ACIK' if enabled else 'kapali'}.")

    @property
    def wake_word_enabled(self) -> bool:
        return self._wake_enabled

    def interrupt_speaking(self) -> None:
        """JARVIS'i konusurken susturur (El Kontrolu ✊, /api/control interrupt).

        Calan ses tamponu bosaltilir ve bu turun geri kalan sesi atilir; bir sonraki tur
        (turn_complete sonrasi) normal calar. Cevrimdisi TTS dongusu de durur.
        """
        loop = getattr(self, "_loop", None)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            # baska bir thread'den (HTTP isleyicisi) cagrildi: asyncio kuyruguna guvenli eris
            loop.call_soon_threadsafe(self.interrupt_speaking)
            return
        self._discard_audio = True
        self._offline_stop = True
        self._drain_playback()
        logger.info("JARVIS susturuldu (interrupt).")

    def set_output_muted(self, muted: bool) -> None:
        """PC hoparlorunu sustur/ac. Telefondan gorusurken ('uzak mod') kullanilir:
        model yaniti yine uretilir ve transkript telefona akar, ama bu makinede ses calmaz."""
        self._output_muted = bool(muted)
        logger.info(f"PC hoparloru {'susturuldu (uzak mod)' if muted else 'acildi'}.")

    @property
    def output_muted(self) -> bool:
        return self._output_muted

    def _tools(self) -> list[types.Tool]:
        """Modele verilen araclar; JARVIS_TOOLS_OFF ile kapatilan gruplar haric."""
        off = set(getattr(self.settings, "tool_groups_disabled", ()) or ())
        return get_tools(off) if off else get_tools()

    def retry_audio(self) -> bool:
        """Ses cihazlarini yeniden acmayi dener (arayuzden cagrilir)."""
        if self.audio_transport.is_open:
            return True
        try:
            self.audio_transport.open(attempts=2, delay=1.0)
            self._audio_ok = True
            logger.success("Ses cihazlari geri geldi.")
            self._notify("on_connection", "active" if self.session is not None else "closed")
            return True
        except RuntimeError as exc:
            logger.warning(f"Ses hala acilamiyor: {exc}")
            return False

    def set_webcam_streaming(self, enabled: bool) -> None:
        self._webcam_streaming = bool(enabled)
        # Kamera donanimini ancak istenildiginde ac; ilk acilista kapali baslar.
        if self._owns_webcam:
            if enabled and not self.webcam.running:
                self.webcam.start()
            elif not enabled and self.webcam.running:
                self.webcam.stop()
        logger.info(f"Webcam akisi {'acik' if enabled else 'kapali'}.")

    def set_screen_streaming(self, enabled: bool) -> None:
        self._screen_streaming = bool(enabled)
        if self._owns_screen:
            if enabled and not self.screen.running:
                self.screen.start()
            elif not enabled and self.screen.running:
                self.screen.stop()
        logger.info(f"Ekran gorusu {'acik' if enabled else 'kapali'}.")

    def inject_bridge_message(self, text: str) -> None:
        """Arayuzden gelen metni harici ajan koprusu gibi outbox'a yazar.

        Canli oturum yoksa (internet yok / Live koptu) ve yerel model aciksa metin outbox'ta
        beklemez: yerel modelle yazili olarak yanitlanir (`core/offline_chat.py`).
        """
        text = (text or "").strip()
        if not text:
            return
        if self.session is None and self._get_offline_chat() is not None:
            asyncio.get_running_loop().create_task(self._offline_reply(text))
            return
        path = self.settings.bridge_outbox_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def _get_offline_chat(self) -> Any:
        if self._offline_chat is None:
            from core.local_llm import get_local_llm

            local = get_local_llm()
            if local is None:
                return None
            from core.offline_chat import OfflineChat

            self._offline_chat = OfflineChat(
                self.tool_runner, local, notify=self._notify,
                log_conversation=self._log_conversation,
            )
        return self._offline_chat

    def _warm_local_model(self) -> None:
        """Internet gitti: yerel modeli arka planda bellege al (ilk yazili yanit hizli olsun)."""
        from core.local_llm import get_local_llm

        local = get_local_llm()
        if local is not None:
            asyncio.get_running_loop().create_task(local.warm_up())

    # ------------------------------------------------------------ cevrimdisi ses

    def _offline_status(self) -> str:
        return "offline-voice" if self._offline_listening else "offline"

    def _start_offline_voice(self) -> None:
        """Internet yok: mikrofonu yerel sesli sohbete bagla (zaten calisiyorsa dokunma)."""
        if self._offline_voice_task is not None or not self.settings.offline_voice_enabled:
            return
        voice = self._offline_voice_io
        if voice is not None and voice.failed:
            return  # yerel STT/TTS yok: her yeniden baglanmada tekrar deneme
        if not self.audio_transport.is_open or self._get_offline_chat() is None:
            return
        self._offline_voice_task = asyncio.get_running_loop().create_task(
            self._offline_voice(), name="offline_voice"
        )

    async def _stop_offline_voice(self) -> None:
        task, self._offline_voice_task = self._offline_voice_task, None
        self._offline_listening = False
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        # thread'de suren son mikrofon okumasi bitsin (akisi ayni anda iki okuyan olmasin)
        await asyncio.sleep(0.15)
        self._playback_active.clear()
        self._speaking = False

    async def _offline_voice(self) -> None:
        """Mikrofon -> vosk -> yerel model (OfflineChat) -> yerel TTS -> hoparlor."""
        try:
            if self._offline_voice_io is None:
                from core.offline_voice import build_offline_voice

                self._offline_voice_io = build_offline_voice(self.settings)
            voice = self._offline_voice_io
            if not await asyncio.to_thread(voice.load):
                self._offline_voice_task = None
                return
            logger.info("Cevrimdisi sesli sohbet dinliyor (yerel model).")
            self._offline_listening = True
            self._notify("on_connection", "offline-voice")
            voice.stt.reset()
            chunk = self.settings.audio.chunk_size
            while True:
                data = await self.audio_transport.read_chunk(chunk)
                if self._mic_muted or self._playback_active.is_set():
                    self._notify("on_input_level", 0.0)
                    continue
                level = _rms_level(data)
                self._notify("on_input_level", level)
                heard = [data]
                if self._wake_enabled and await self._wake_ready():
                    preroll: list[bytes] = []
                    if not await self._gate_audio(data, data, level, sink=preroll.append):
                        heard = preroll  # uykuda bos; uyanis aninda cumlenin basi
                text = None
                for pcm in heard:
                    text = await asyncio.to_thread(voice.stt.feed, pcm) or text
                if not text:
                    continue
                self._gate.touch()
                logger.info(f"Kullanici (yerel): {text}")
                self._notify("on_user_transcript", text, True)
                answer = await self._offline_chat.reply(text)
                await self._speak_offline(voice, answer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - cevrimdisi ses motoru dusurmez
            logger.error(f"Cevrimdisi sesli sohbet durdu: {exc!r}")
            self._offline_voice_task = None
            self._offline_listening = False
            self._notify("on_connection", "offline")

    async def _speak_offline(self, voice: Any, text: str) -> None:
        pcm = await asyncio.to_thread(voice.tts.synthesize, text)
        if not pcm:
            return
        audio = self.settings.audio
        bytes_per_s = audio.receive_sample_rate * audio.sample_width
        step = int(bytes_per_s * _OFFLINE_TTS_STEP_S)
        self._playback_active.set()  # eko engelleme: kendi sesimizi dinleme
        self._speaking = True
        self._offline_stop = False
        self._notify("on_state", "speaking")
        try:
            for start in range(0, len(pcm), step):
                if self._offline_stop:
                    break
                part = pcm[start:start + step]
                self._gate.keep_awake(fresh=False)
                self._notify("on_output_level", _rms_level(part))
                if self._output_muted:
                    await asyncio.sleep(len(part) / bytes_per_s)
                else:
                    await self.audio_transport.write_chunk(part)
        finally:
            await asyncio.sleep(0.15)
            voice.stt.reset()
            self._playback_active.clear()
            self._speaking = False
            self._notify("on_output_level", 0.0)
            self._notify("on_state", "idle")

    async def _offline_reply(self, text: str) -> None:
        try:
            await self._offline_chat.reply(text)
        except Exception:  # noqa: BLE001 - sohbet hatasi motoru dusurmez
            logger.exception("Cevrimdisi sohbet hatasi")
            self._notify("on_assistant_transcript", "(yerel) Bir hata olustu.", True)

    @property
    def session_active(self) -> bool:
        return self.session is not None

    async def send_user_text(self, text: str) -> bool:
        """Yazili bir kullanici mesajini canli oturuma DOGRUDAN verir (sunucu /command).

        Kopru dosyasindan farkli olarak `[KOPRU]` on-eki eklemez ve 0.5 sn yoklama
        beklemez; model bunu kullanicinin yazdigi bir mesaj olarak gorur. Oturum yoksa
        False doner (cagiran taraf net bir hata vermelidir).
        """
        text = (text or "").strip()
        session = self.session
        if not text or session is None:
            return False
        self._notify("on_user_transcript", text, True)
        self._log_conversation("user", text)
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )
        return True

    @property
    def mic_muted(self) -> bool:
        return self._mic_muted

    @property
    def webcam_streaming(self) -> bool:
        return self._webcam_streaming

    @property
    def screen_streaming(self) -> bool:
        return self._screen_streaming

    # ================================================================= lifecycle

    async def _probe_adb(self) -> None:
        """Android ADB modulunu asenkron olarak yoklar (non-fatal).

        ADB bulunamazsa / cihaz bagli degilse motor calismaya devam eder; durum
        yalnizca loglanir ve ilgili araclar cagrildiginda kullanici dostu hata doner.
        """
        try:
            await self.adb.probe()
        except Exception as exc:  # noqa: BLE001 - ADB motoru cokertemez
            logger.warning(f"ADB yoklamasi basarisiz (yok sayiliyor): {exc!r}")

    async def run(self) -> None:
        logger.info("BrainEngine baslatiliyor...")
        self._loop = asyncio.get_running_loop()
        try:
            self.audio_transport.open()
        except RuntimeError as exc:
            # Ses cihazi acilmadi (baska uygulama tutuyor / gizlilik). Sesiz devam:
            # canli oturum, ekran gorusu, araclar ve ajanlar yine calisir.
            self._audio_ok = False
            logger.error(f"SES DEVRE DISI - {exc}. Sesli mod olmadan devam ediliyor.")
            self._notify("on_connection", "no-audio")
        if self._owns_webcam and self.settings.webcam_enabled:
            self.webcam.start()
        if self._owns_screen and self.settings.screen_enabled:
            self.screen.start()

        await self._probe_adb()

        attempt = 0
        try:
            while not self._shutdown.is_set():
                failed = False
                try:
                    await self._connect_and_run()
                    attempt = 0
                except (KeyboardInterrupt, asyncio.CancelledError):
                    raise
                except BaseExceptionGroup as group:
                    switch, rest = group.split(_PersonaSwitch)
                    non_cancel = None
                    if rest is not None:
                        non_cancel, _ = rest.split(
                            lambda e: not isinstance(e, asyncio.CancelledError)
                        )
                    if self._shutdown.is_set():
                        break
                    if switch is not None and non_cancel is None:
                        # hata degil: beklemeden yeni kisilikle baglan
                        attempt = 0
                        logger.info("Yeni kisilikle yeniden baglaniliyor...")
                        continue
                    attempt += 1
                    failed = True
                    self._log_exception_group(non_cancel or group)
                    self._check_setup_rejection(non_cancel or group)
                    attempt = self._settle_after_failure(non_cancel or group, attempt)
                    if non_cancel is not None and non_cancel.subgroup(_is_audio_error):
                        # Ses akisi oldu: oturumu yenilemek yetmez, akislar da yeniden
                        # acilmazsa her yanitta yine 'Stream closed' ile duser.
                        self._recover_audio()
                        attempt = 1
                except Exception as exc:  # noqa: BLE001
                    attempt += 1
                    failed = True
                    logger.error(f"Oturum hatasi: {exc!r}")
                    self._check_setup_rejection(exc)
                    attempt = self._settle_after_failure(exc, attempt)

                if self._shutdown.is_set():
                    break
                if (
                    self.settings.reconnect_max_attempts
                    and attempt > self.settings.reconnect_max_attempts
                ):
                    logger.critical("Maksimum yeniden baglanma denemesi asildi. Cikiliyor.")
                    break

                delay = self._backoff_delay(attempt)
                from core.connectivity import is_online

                online = await is_online(force=True)
                self._note_resume_outcome(failed and not self._attempt_active, online)
                if not online:
                    self._start_offline_voice()
                self._notify("on_connection", "reconnecting" if online else self._offline_status())
                if not online and not self._local_warmed:
                    self._local_warmed = True
                    self._warm_local_model()
                elif online:
                    self._local_warmed = False
                logger.warning(f"{delay:.1f} sn sonra yeniden baglanilacak (deneme {attempt}).")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._shutdown.wait(), timeout=delay)
        finally:
            await self.aclose()

    async def _connect_and_run(self) -> None:
        self._reset_queues()
        self._persona_switch.clear()  # baglanmadan once gelen secim zaten uygulanacak
        self._attempt_active = False
        if self._resume_handle and time.monotonic() - self._resume_saved_at > _RESUME_TTL_S:
            self._drop_resume_handle("suresi doldu")
        resuming = bool(self._resume_handle)
        config = self._build_config()
        logger.info(f"Gemini Live'a baglaniliyor: {self.settings.model}"
                    f"{' (onceki oturum devam ettiriliyor)' if resuming else ''}")
        if not self._offline_listening:
            self._notify("on_connection", "connecting")
        self._connect_started = time.monotonic()

        async with self.client.aio.live.connect(
            model=self.settings.model, config=config
        ) as session:
            await self._stop_offline_voice()  # mikrofonu _listen_audio devralir
            self.session = session
            self._attempt_active = True
            self._resume_failures = 0
            logger.success("Gemini Live oturumu AKTIF.")
            self._notify("on_connection", "active")
            self._notify("on_state", "idle")
            try:
                async with asyncio.TaskGroup() as task_group:
                    task_group.create_task(self._send_realtime(), name="send_realtime")
                    task_group.create_task(self._listen_audio(), name="listen_audio")
                    task_group.create_task(self._receive_audio(), name="receive_audio")
                    task_group.create_task(self._play_audio(), name="play_audio")
                    task_group.create_task(
                        self._stream_webcam_frames(), name="stream_webcam_frames"
                    )
                    task_group.create_task(
                        self._stream_screen_frames(), name="stream_screen_frames"
                    )
                    task_group.create_task(
                        self._watch_bridge_inbox(), name="watch_bridge_inbox"
                    )
                    task_group.create_task(
                        self._watch_persona_switch(), name="watch_persona_switch"
                    )
            finally:
                self.session = None
                self._playback_active.clear()
                self._speaking = False
        logger.info("Gemini Live oturumu kapandi.")
        self._notify("on_connection", "closed")

    # ================================================================= 6 gorev

    async def _send_realtime(self) -> None:
        """out_queue'daki mikrofon/webcam paketlerini canli oturuma iletir."""
        while True:
            kind, blob = await self.out_queue.get()
            session = self.session
            if session is None:
                continue
            try:
                if kind == "audio_end":
                    # uyandirma kapisi uykuya gecti: konusma bitti, sunucu VAD'i beklemesin
                    with contextlib.suppress(Exception):
                        await session.send_realtime_input(audio_stream_end=True)
                elif kind == "audio":
                    await session.send_realtime_input(audio=blob)
                else:
                    await session.send_realtime_input(video=blob)
            except TypeError:
                # Eski google-genai surumleri: birlesik 'media' argumani
                await session.send_realtime_input(media=blob)

    async def _listen_audio(self) -> None:
        """Audio transport'tan 16 kHz PCM ses yakalar. Model konusurken / sessizdeyken susar."""
        if not self.audio_transport.is_open:
            logger.error("Mikrofon kaynagi yok, _listen_audio devre disi.")
            return

        chunk = self.settings.audio.chunk_size
        mime = f"audio/pcm;rate={self.settings.audio.send_sample_rate}"
        was_muted = False
        while True:
            data = await self.audio_transport.read_chunk(chunk)
            muted = self._mic_muted or self._bridge_held()
            if muted and not was_muted:
                # Konusma ortasinda susturulursa sunucu VAD'i konusmanin bittigini
                # hic duymaz ve yanit vermeden bekler: akisin bittigini bildir.
                with contextlib.suppress(asyncio.QueueFull):
                    self.out_queue.put_nowait(("audio_end", None))
            was_muted = muted
            if self._playback_active.is_set() or self._mic_muted:
                self._notify("on_input_level", 0.0)
                continue  # EKO ENGELLEME / manuel susturma
            level = _rms_level(data)
            self._notify("on_input_level", level)
            blob = types.Blob(data=data, mime_type=mime)
            if self._wake_enabled and await self._wake_ready():
                # kopru bekletmesinde kapi uykudadir: yalniz "Hey JARVIS" sesi iceri alir
                if not await self._gate_audio(data, blob, level):
                    continue  # uykuda: ses modele GITMEZ
            elif self._bridge_held():
                continue  # kopru mesaji yanitlaniyor: ortam sesi yaniti bolmesin
            self._queue_audio(blob)

    def _queue_audio(self, blob: Any) -> None:
        try:
            self.out_queue.put_nowait(("audio", blob))
        except asyncio.QueueFull:
            logger.debug("out_queue dolu, ses paketi dusuruldu.")

    def _init_speaker_verify(self) -> None:
        settings = self.settings
        if not settings.speaker_verify_enabled:
            return
        from core.speaker_verify import SpeakerGate, build_speaker_verifier

        audio = settings.audio
        bytes_per_s = audio.send_sample_rate * audio.sample_width
        self._speaker = build_speaker_verifier(settings)
        self._speaker_gate = SpeakerGate(int(bytes_per_s * _SPEAKER_SEGMENT_S))
        chunk_s = audio.chunk_size / audio.send_sample_rate
        self._recent_pcm = collections.deque(maxlen=max(1, round(_SPEAKER_WAKE_S / chunk_s)))

    @property
    def _speaker_active(self) -> bool:
        return self._speaker is not None and bool(self._speaker.available)

    async def _wake_ready(self) -> bool:
        """Detektoru gerekirse yukler; kullanilamiyorsa kapi devre disi (her zaman dinle)."""
        if self._wake.available is None:
            ok = await asyncio.to_thread(self._wake.load)
            self._notify("on_wake", not ok)  # yuklendiyse uykuda baslar
            if ok and self._speaker is not None:
                await asyncio.to_thread(self._speaker.load)  # profil yoksa pasif kalir
        return bool(self._wake.available)

    async def _wake_speaker_ok(self) -> bool:
        """'Hey JARVIS'i kayitli ses mi soyledi? Dogrulama pasifse her zaman True."""
        if not self._speaker_active:
            return True
        score = await asyncio.to_thread(self._speaker.score, b"".join(self._recent_pcm))
        if score >= self._speaker.threshold - _SPEAKER_WAKE_MARGIN:
            return True
        logger.info(f"Uyandirma kelimesi baska bir sesten geldi (ses izi {score:.2f} < "
                    f"{self._speaker.threshold - _SPEAKER_WAKE_MARGIN:.2f}); yok sayildi.")
        return False

    def _verify_ongoing(self, data: bytes) -> None:
        """Pencere acikken: dilim dolunca arka planda dogrula (ses akisini bekletmez)."""
        segment = self._speaker_gate.add(data)
        if segment is None or (self._speaker_task is not None and not self._speaker_task.done()):
            return
        self._speaker_task = asyncio.get_running_loop().create_task(self._judge_segment(segment))

    async def _judge_segment(self, segment: bytes) -> None:
        try:
            score = await asyncio.to_thread(self._speaker.score, segment)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Ses izi degerlendirilemedi: {exc!r}")
            return
        matched = score >= self._speaker.threshold
        if matched:
            self._gate.touch()  # pencereyi yalniz dogrulanmis konusma uzatir
        if self._speaker_gate.record(matched) and self._gate.awake:
            logger.info(f"Konusan kayitli ses degil (ses izi {score:.2f}); dinleme kapatildi.")
            self._gate.sleep()

    async def _gate_audio(
        self, data: bytes, blob: Any, level: float,
        sink: Callable[[Any], None] | None = None,
    ) -> bool:
        """Uyandirma kapisi. True => bu parca simdi modele gonderilmeli.

        Uyanista on-dolum parcalari `sink`'e (varsayilan: canli oturum kuyrugu) verilir.
        """
        gate = self._gate
        self._report_wake()  # uyanma/uyuma gecisini arayuze bildir
        if gate.awake:
            if level >= _WAKE_SPEECH_LEVEL:
                if self._speaker_active:
                    self._verify_ongoing(data)
                else:
                    gate.touch()
            return True
        gate.remember(blob)
        if self._speaker is not None:
            self._recent_pcm.append(data)  # uyanista ses izi icin son ~1.5 sn
        score = await asyncio.to_thread(self._wake.score, data)
        if score < self.settings.wake_word_threshold:
            self._log_near_miss(score)
            return False
        self._wake.reset()
        if not await self._wake_speaker_ok():
            return False
        logger.info(f"Uyandirma kelimesi algilandi (skor {score:.2f}).")
        if self._speaker_gate is not None:
            self._speaker_gate.reset()
        self._bridge_hold_until = 0.0  # kullanici acikca seslendi: bekletme biter
        self._no_followup = False
        for chunk in gate.wake():  # on-dolum (bu parca dahil): cumlenin basi kaybolmasin
            (sink or self._queue_audio)(chunk)
        self._report_wake()
        return False

    def _log_near_miss(self, score: float) -> None:
        """Esigi kil payi kacan skorlar: gercek kullanimda esik ayari icin iz (5 sn'de en fazla 1)."""
        if score < _WAKE_NEAR_MISS:
            return
        now = asyncio.get_running_loop().time()
        if now - self._last_near_miss < _WAKE_NEAR_MISS_EVERY_S:
            return
        self._last_near_miss = now
        logger.info(f"Uyandirma neredeyse algilandi: skor {score:.2f} "
                    f"(esik {self.settings.wake_word_threshold:.2f}).")

    def _report_wake(self) -> None:
        changed = self._gate.transition()
        if changed is None:
            return
        self._notify("on_wake", changed)
        if not changed:
            logger.debug("Uyandirma penceresi kapandi - uykuda ('Hey JARVIS' bekleniyor).")
            with contextlib.suppress(asyncio.QueueFull):
                self.out_queue.put_nowait(("audio_end", None))

    async def _receive_audio(self) -> None:
        """Gemini yanitlarini, transkriptleri ve tool_call isteklerini dinler."""
        session = self.session
        if session is None:
            raise RuntimeError("Oturum yok - _receive_audio baslatilamaz.")

        while True:
            turn = session.receive()
            async for response in turn:
                if getattr(response, "data", None) and not self._discard_audio:
                    self.audio_in_queue.put_nowait(response.data)

                server_content = getattr(response, "server_content", None)
                if server_content is not None:
                    self._handle_server_content(server_content)

                tool_call = getattr(response, "tool_call", None)
                if tool_call is not None:
                    await self._handle_tool_call(tool_call)

                update = getattr(response, "session_resumption_update", None)
                if update is not None:
                    self._on_resumption_update(update)
                go_away = getattr(response, "go_away", None)
                if go_away is not None:
                    logger.info(f"Sunucu oturumu kapatacak (kalan {go_away.time_left}); "
                                "yeniden baglaninca kaldigi yerden devam edilecek.")

    async def _play_audio(self) -> None:
        """Gemini'dan gelen 24 kHz PCM sesi audio transport uzerinden calar."""
        if not self.audio_transport.is_open:
            logger.error("Hoparlor kaynagi yok, _play_audio devre disi.")
            return

        while True:
            chunk = await self.audio_in_queue.get()
            if not self._speaking:
                self._speaking = True
                self._notify("on_state", "speaking")
            self._playback_active.set()
            if not self._no_followup and not self._bridge_held():
                # model konusuyor: bitince kullanici "Hey JARVIS"siz cevap verebilsin
                self._gate.keep_awake(fresh=False)
            fx = self._fx
            if fx is not None:
                chunk = fx.process(chunk)  # uzunluk degismez (eko zamanlamasi)
            self._notify("on_output_level", _rms_level(chunk))
            if self._output_muted:
                # Uzak mod: sesi calma ama konusma suresi kadar bekle ki
                # eko engelleme (_playback_active) zamanlamasi bozulmasin.
                audio = self.settings.audio
                await asyncio.sleep(
                    len(chunk) / (audio.receive_sample_rate * audio.sample_width)
                )
            else:
                await self.audio_transport.write_chunk(chunk)
            if self.audio_in_queue.empty():
                await asyncio.sleep(0.15)  # kisa sessizlik sonrasi mikrofonu tekrar ac
                if self.audio_in_queue.empty():
                    self._playback_active.clear()
                    self._speaking = False
                    self._notify("on_output_level", 0.0)
                    self._notify("on_state", "idle")

    async def _stream_webcam_frames(self) -> None:
        """Kamera aktifken belirli araliklarla en guncel JPEG karesini modele iletir."""
        interval = self.settings.webcam_interval
        while True:
            await asyncio.sleep(interval)
            if not self._webcam_streaming:
                continue
            jpeg = self.webcam.get_latest_jpeg()
            if not jpeg:
                continue
            blob = types.Blob(data=jpeg, mime_type="image/jpeg")
            try:
                self.out_queue.put_nowait(("video", blob))
            except asyncio.QueueFull:
                logger.debug("out_queue dolu, webcam karesi dusuruldu.")

    async def _stream_screen_frames(self) -> None:
        """Ekran gorusu acikken belirli araliklarla ekran goruntusunu modele iletir."""
        interval = self.settings.screen_interval
        while True:
            await asyncio.sleep(interval)
            if not self._screen_streaming:
                continue
            jpeg = self.screen.get_latest_jpeg()
            if not jpeg:
                continue
            blob = types.Blob(data=jpeg, mime_type="image/jpeg")
            try:
                self.out_queue.put_nowait(("video", blob))
            except asyncio.QueueFull:
                logger.debug("out_queue dolu, ekran karesi dusuruldu.")

    async def _watch_bridge_inbox(self) -> None:
        """bridge/outbox.txt'e yazilan mesajlari canli oturuma enjekte eder.

        Kaynaklar: ajan sonuclari ([Departman] ...), telefon ([TELEFON] ...),
        hatirlatici ([HATIRLATICI] ...), rutin ([RUTIN:...] ...).
        """
        async for message in self.bridge.messages():
            session = self.session
            if session is None:
                continue
            logger.info(f"Kopru mesaji enjekte ediliyor: {message}")
            self._notify("on_bridge_message", message)
            self._log_bridge_conversation(message)
            self._hold_for_bridge(message)
            if message.lstrip().startswith("["):
                text = message  # kaynak on-eki zaten var
            else:
                text = f"[KOPRU] {message}"
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True,
            )

    # ================================================================= yardimcilar

    def _bridge_held(self) -> bool:
        return time.monotonic() < self._bridge_hold_until

    def _hold_for_bridge(self, message: str) -> None:
        """Kopru mesaji yanitlanana kadar mikrofonu modele kapatir.

        Enjekte edilen tur da sesle bolunebilir: 6 Ekim'de odadaki sohbet, telefondan gelen
        soruyu defalarca kesti ve soru dakikalarca yanitsiz kaldi. Bekletme, bu mesajin
        yanit turu bitince (`_release_bridge_hold`) ya da `bridge_hold_s` dolunca kalkar;
        uyandirma kelimesi aciksa "Hey JARVIS" hemen kaldirir.
        """
        self._discard_audio = False  # yeni istek: onceki susturma bunun yanitini kesmesin
        if message.lstrip().startswith(_GESTURE_SOURCE):
            # El jesti: kullanici PC basinda; mikrofonu kapatma, yanittan sonra dinlesin
            self._no_followup = False
            self._gate.keep_awake()
            return
        self._no_followup = message.lstrip().startswith(_REMOTE_SOURCES)
        hold = float(self.settings.bridge_hold_s)
        if hold <= 0:
            if not self._no_followup:
                self._gate.keep_awake()  # bekletme kapali: yanit icin pencereyi simdi ac
            return
        # su an acik bir model turu varsa onun turn_complete'i bu mesajin yaniti degildir
        self._bridge_skip_turns = 1 if (self._model_transcript or self._turn_tools) else 0
        self._bridge_hold_until = time.monotonic() + hold
        self._gate.sleep()

    def _release_bridge_hold(self) -> None:
        if not self._bridge_held():
            return
        if self._bridge_skip_turns > 0:
            self._bridge_skip_turns -= 1
            return
        self._bridge_hold_until = 0.0
        if not self._no_followup:
            self._gate.keep_awake()  # hatirlatici / ajan sonucu: kullanici cevap verebilsin

    def _handle_server_content(self, server_content: Any) -> None:
        if getattr(server_content, "interrupted", None):
            logger.info("Kullanici modeli boldu - ses tamponu temizleniyor.")
            self._drain_playback()

        input_tx = getattr(server_content, "input_transcription", None)
        if input_tx is not None and getattr(input_tx, "text", None):
            self._user_transcript += input_tx.text
            self._no_followup = False  # kullanici PC basinda konusuyor
            if not self._speaker_active:  # dogrulama acikken pencereyi yalniz dogrulanmis ses uzatir
                self._gate.touch()
            if not self._playback_active.is_set():
                self._notify("on_state", "listening")
            self._notify("on_user_transcript", self._user_transcript.strip(), False)

        output_tx = getattr(server_content, "output_transcription", None)
        if output_tx is not None and getattr(output_tx, "text", None):
            self._model_transcript += _CTRL_TOKEN_RE.sub("", output_tx.text)
            self._notify("on_assistant_transcript", self._model_transcript.strip(), False)

        if getattr(server_content, "turn_complete", None):
            user_final = self._user_transcript.strip()
            model_final = _CTRL_TOKEN_RE.sub("", self._model_transcript).strip()
            if user_final:
                logger.info(f"Kullanici : {user_final}")
                self._notify("on_user_transcript", user_final, True)
                self._log_conversation("user", user_final)
            if model_final:
                logger.info(f"JARVIS    : {model_final}")
                self._notify("on_assistant_transcript", model_final, True)
                self._log_conversation("jarvis", model_final)
            self._user_transcript = ""
            self._model_transcript = ""
            self._turn_tools = False
            self._discard_audio = False  # susturulan tur bitti: sonraki yanit calsin
            self._release_bridge_hold()

    def _log_conversation(self, role: str, text: str) -> None:
        """Bir konusma turunu Obsidian kasasina (Konusmalar/) arka planda ekler."""
        if not self.settings.obsidian_log_conversations or not (text or "").strip():
            return
        try:
            from tools.obsidian_sync import append_conversation

            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(append_conversation, role, text))
        except RuntimeError:
            pass  # calisan dongu yok
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Konusma kaydi planlanamadi: {exc}")

    def _log_bridge_conversation(self, message: str) -> None:
        """Kopru mesajlarini konusma kaydina uygun rol/metinle isler."""
        low = message.lstrip()
        if low.startswith("[TELEFON BILDIRIMI]"):
            return  # bildirim aynasi - konusma degil
        if low.startswith("[TELEFON]"):
            self._log_conversation("telefon", low.split("]", 1)[1])
        elif low.startswith(_GESTURE_SOURCE):
            self._log_conversation("el", low.split("]", 1)[1])
        elif low.startswith("[HATIRLATICI]"):
            self._log_conversation("hatirlatici", low.split("]", 1)[1])
        elif low.startswith("["):
            self._log_conversation("ajan", message)
        else:
            self._log_conversation("kopru", message)

    async def _handle_tool_call(self, tool_call: Any) -> None:
        calls = list(getattr(tool_call, "function_calls", None) or [])
        if not calls:
            return
        names = [c.name for c in calls]
        self._turn_tools = True
        self._gate.touch()
        logger.info(f"Arac cagrisi: {names}")
        self._notify("on_tool_call", names)

        responses = await asyncio.gather(
            *(self.tool_runner.dispatch(call) for call in calls)
        )
        for call, resp in zip(calls, responses):
            payload = getattr(resp, "response", None) or {}
            ok = "error" not in payload
            detail = str(payload.get("error") if not ok else payload)
            self._notify("on_tool_result", call.name or "?", ok, detail[:200])

        session = self.session
        if session is not None:
            await session.send_tool_response(function_responses=list(responses))
            logger.debug("Arac yanitlari modele iletildi.")

    def _drain_playback(self) -> None:
        while not self.audio_in_queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.audio_in_queue.get_nowait()
        self._playback_active.clear()
        self._speaking = False
        self._notify("on_output_level", 0.0)
        self._notify("on_state", "idle")

    def _reset_queues(self) -> None:
        self.out_queue = asyncio.Queue(maxsize=200)
        self.audio_in_queue = asyncio.Queue()
        if not self._offline_listening:  # cevrimdisi ses konusuyorsa eko engeli kalsin
            self._playback_active.clear()
            self._speaking = False
        self._user_transcript = ""
        self._model_transcript = ""
        self._turn_tools = False
        self._bridge_hold_until = 0.0
        self._bridge_skip_turns = 0
        self._discard_audio = False

    def _backoff_delay(self, attempt: int) -> float:
        base = self.settings.reconnect_base_delay
        cap = self.settings.reconnect_max_delay
        delay = min(cap, base * (2 ** max(0, attempt - 1)))
        return delay + random.uniform(0, min(1.0, delay * 0.25))

    def _notify(self, method: str, *args: Any) -> None:
        try:
            getattr(self.observer, method)(*args)
        except Exception:  # noqa: BLE001 - gozlemci hatasi motoru cokertemez
            logger.exception(f"Observer hatasi: {method}")

    def _show_panel(self, payload: dict[str, Any]) -> bool:
        """Icerik panelini arayuze iletir; arayuz gosterebildiyse True."""
        try:
            return bool(self.observer.on_panel(payload))
        except Exception:  # noqa: BLE001 - gozlemci hatasi motoru cokertemez
            logger.exception("Observer hatasi: on_panel")
            return False

    def _request_exit(self) -> None:
        """Model 'exit_application' araciyla uygulamayi kapatmak istedi."""
        logger.info("Uygulama kapatma istegi (arac).")
        self._notify("on_exit_request")
        self.request_shutdown()

    def _confirm(self, prompt: str) -> bool:
        """Kullanici onayi ister (arac thread'inden bloklayarak cagrilir)."""
        if not self.settings.confirm_before_close:
            return True
        try:
            approved = bool(self.observer.confirm(prompt))
        except Exception:  # noqa: BLE001
            logger.exception("Onay istegi basarisiz")
            return False
        logger.info(f"Onay '{prompt}' -> {'EVET' if approved else 'HAYIR'}")
        return approved

    def _recover_audio(self) -> None:
        """PortAudio hatasindan sonra ses cihazlarini sifirdan acar."""
        logger.warning("Ses akisi bozuldu; ses cihazlari yeniden aciliyor...")
        try:
            self.audio_transport.reopen(attempts=3, delay=1.0)
            self._audio_ok = True
            logger.success("Ses cihazlari yeniden acildi.")
        except RuntimeError as exc:
            self._audio_ok = False
            logger.error(f"SES DEVRE DISI - {exc}. Sesli mod olmadan devam ediliyor.")
            self._notify("on_connection", "no-audio")

    def _on_resumption_update(self, update: Any) -> None:
        """Sunucu yeni bir devam tutamagi verdi: bir sonraki baglanti buradan surer."""
        handle = getattr(update, "new_handle", None)
        if getattr(update, "resumable", None) and handle:
            self._resume_handle = handle
            self._resume_saved_at = time.monotonic()

    def _drop_resume_handle(self, reason: str) -> None:
        if self._resume_handle:
            logger.warning(f"Oturum devam ettirilemiyor ({reason}); temiz oturum acilacak.")
        self._resume_handle = None
        self._resume_failures = 0

    def _note_resume_outcome(self, failed_before_active: bool, online: bool) -> None:
        """Tutamakla baglanma, internet VARKEN art arda iki kez oturum kurulmadan duserse
        tutamak gecersizdir. Internet yokken dusmek tutamagi harcamaz."""
        if not self._resume_handle or not failed_before_active or not online:
            return
        self._resume_failures += 1
        if self._resume_failures >= 2:
            self._drop_resume_handle("sunucu tutamagi kabul etmedi")

    def _settle_after_failure(self, exc: BaseException, attempt: int) -> int:
        """Oturum KURULDUKTAN sonra gelen hata icin deneme sayacini ve tutamagi ayarlar.

        - 1007 (gecersiz istek): sunucudaki oturum durumu bozulmustur; ayni devam tutamagiyla
          donmek her turda yine 1007 verir. Tutamak birakilir, temiz oturum acilir.
        - Oturum bir sure saglikli calistiysa geri cekilme bastan baslar (bekleme uzamaz).
        """
        if not self._attempt_active:
            return attempt
        if "1007" in repr(exc) and self._resume_handle:
            self._drop_resume_handle("oturum ortasinda 1007 (gecersiz istek)")
        if time.monotonic() - self._connect_started >= _STABLE_SESSION_S:
            return 1
        return attempt

    def _check_setup_rejection(self, exc: BaseException) -> None:
        """Sunucu oturum ayarini (1007 invalid argument) baglanir baglanmaz reddettiyse
        istege bagli 'proactive audio' alanini kapatir; sonraki deneme onsuz baglanir."""
        if not self._proactive_audio or "1007" not in repr(exc):
            return
        if self._resume_handle:
            return  # once devam tutamagi elenir (_note_resume_outcome)
        if time.monotonic() - self._connect_started > _SETUP_REJECT_S:
            return  # oturum ortasinda gelen 1007 baska bir sorundur
        self._proactive_audio = False
        logger.warning(
            "Model 'proactive audio' ayarini kabul etmedi; bu calismada kapatildi "
            "(kalici kapatmak icin JARVIS_PROACTIVE_AUDIO=false)."
        )

    @staticmethod
    def _log_exception_group(group: BaseException) -> None:
        excs = getattr(group, "exceptions", [group])
        for exc in excs:
            logger.error(f"TaskGroup gorev hatasi: {exc!r}")

    def _build_config(self) -> types.LiveConnectConfig:
        persona = self._persona or personas.get(self.settings, None)
        system_prompt = self.settings.load_system_prompt(persona.key)
        if self.settings.session_context_enabled and not self._resume_handle:
            # temiz oturum: tarih/saat + dunun ozeti + bugunku son konusmalar
            from core.session_context import build_context

            system_prompt = f"{system_prompt}\n\n{build_context(self.settings)}"
        base: dict[str, Any] = dict(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                role="user", parts=[types.Part(text=system_prompt)]
            ),
            tools=self._tools(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=persona.voice_name
                    ),
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        try:
            extra: dict[str, Any] = {
                # handle=None da olsa acik kalir: sunucu devam tutamaklari gondermeye baslar
                "session_resumption": types.SessionResumptionConfig(handle=self._resume_handle),
            }
            if self._proactive_audio:
                # model, kendisine hitap edilmeyen konusmaya (ortam sohbeti, TV) yanit vermeyebilir
                extra["proactivity"] = types.ProactivityConfig(proactive_audio=True)
            return types.LiveConnectConfig(
                **base,
                **extra,
                context_window_compression=types.ContextWindowCompressionConfig(
                    sliding_window=types.SlidingWindow(),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - surum uyumsuzlugu
            logger.debug(f"Gelismis config alanlari atlandi: {exc!r}")
            return types.LiveConnectConfig(**base)

    async def aclose(self) -> None:
        self._shutdown.set()
        await self._stop_offline_voice()
        if self._owns_webcam:
            with contextlib.suppress(Exception):
                self.webcam.stop()
        if self._owns_screen:
            with contextlib.suppress(Exception):
                self.screen.stop()
        with contextlib.suppress(Exception):
            self.audio_transport.shutdown()
        # MCP oturumlari + kontrollu tarayici (acilmadiysa anlik doner)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(get_worker().shutdown)
        self._notify("on_connection", "closed")
        logger.info("BrainEngine kapatildi.")
