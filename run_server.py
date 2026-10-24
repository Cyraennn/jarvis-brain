"""Lab bilgisayarinda GUI'siz calisan CYRAEN sunucusu ("server modu").

`main.py` (sessiz/headless) motoru calistirir ama HICBIR disaridan kontrol
arayuzu acmaz. Bu giris noktasi, ev bilgisayarindan (Tailscale uzerinden) TAM
kontrol icin gerekenleri ekler:

  - Web konsolu (`web/console_server.py`)  : komut gonderme, durum izleme,
    mikrofon/uzak-mod, VE onay/red (`/api/confirm`).
  - Uzak ses sunucusu (`net/audio_server.py`): `CYRAEN_AUDIO_MODE=network` ise
    mikrofon/hoparlor BU makinede DEGIL, `remote_client/run_remote_client.py`
    calisan ev bilgisayarindadir.
  - Ajan orkestratoru + zamanlayici: masaustu uygulamasiyla (`ui/app.py`) AYNI
    GUI'siz threading deseni (`OrchestratorWorker`/`WebWorker`/`SchedulerWorker`),
    sadece Qt gozlemcileri yerine `web/web_observer.py`'deki BUS-tabanli
    esdegerleri kullanilir.
  - Onaylar (`confirm_before_close`, `agents_require_approval`): Qt diyalogu
    yerine web konsoluna dusen bekleyen istekler olarak sunulur; cevap gelmezse
    `settings.remote_confirm_timeout` sonunda REDDEDILIR (otomatik onay YOK -
    paylasimli/uzak bir makinede bilincli guvenlik varsayilani).

Kullanim (lab bilgisayarinda):
    python run_server.py
(otomatik baslatma icin `docs/remote_setup.md`'deki Task Scheduler ornegine bakin)
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from loguru import logger

from config.settings import Settings, get_settings
from core.audio_transport import AudioTransport, NetworkAudioTransport
from core.brain_engine import BrainEngine
from core.notifications import build_broadcaster
from core.scheduler_handler import SchedulerHandler
from core.telegram_handler import TelegramHandler
from core.whatsapp_handler import WhatsAppHandler, load_whatsapp_config
from net.audio_server import NetworkAudioServer
from ui.orchestrator_worker import OrchestratorWorker
from ui.web_worker import WebWorker
from web.web_observer import WebEngineObserver, WebOrchestratorObserver


def _configure_logging(settings: Settings) -> None:
    logger.remove()
    if sys.stderr is not None:  # pythonw.exe altinda None olabilir
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format=(
                "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
                "<cyan>{name}:{function}</cyan> - <level>{message}</level>"
            ),
            enqueue=True,
        )
    logger.add(
        settings.log_file,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
    )


def _check_remote_safety(settings: Settings) -> None:
    """Ag-ses modunda tokenlar bossa erken ve gurultulu sekilde reddet.

    Sunucularin kendisi zaten token yoksa bind'i 127.0.0.1'e dusurur (bkz.
    `web/console_server.py:83`, `net/audio_server.py`) - ama bu sessizce
    "sadece bu bilgisayardan erisilebilir" anlamina gelir, ki bu tam olarak
    server modunun ONLEMEYE calistigi durumdur. Burada acikca durduruyoruz.
    """
    if settings.audio_mode != "network":
        return
    missing = [
        name
        for name, val in (
            ("CYRAEN_WEB_TOKEN", settings.web_console_token),
            ("CYRAEN_REMOTE_AUDIO_TOKEN", settings.remote_audio_token),
        )
        if not val
    ]
    if missing:
        raise SystemExit(
            "CYRAEN_AUDIO_MODE=network icin .env'de sunlar DOLU olmali (yoksa "
            "sunucular sessizce sadece bu bilgisayara kapali kalir, ev "
            "bilgisayarindan hicbir sekilde baglanilamaz): " + ", ".join(missing)
        )


def _make_on_control(engine: BrainEngine, loop: asyncio.AbstractEventLoop):
    """`ui/app.py::_on_web_control` ile ayni davranis - ama motor burada farkli
    bir OS thread'inde (WebWorker'in HTTP thread'i) degil, BU asyncio loop'unda
    yasadigi icin degisiklikler `call_soon_threadsafe` ile guvenle marshal edilir."""

    def _on_web_control(action: str) -> dict:
        if action == "mic_off":
            loop.call_soon_threadsafe(engine.set_mic_muted, True)
            return {"mic": False}
        if action == "mic_on":
            loop.call_soon_threadsafe(engine.set_mic_muted, False)
            return {"mic": True}
        if action == "away_on":
            loop.call_soon_threadsafe(engine.set_mic_muted, True)
            loop.call_soon_threadsafe(engine.set_output_muted, True)
            logger.info("Uzak mod ACIK (web konsolundan).")
            return {"away": True}
        if action == "away_off":
            loop.call_soon_threadsafe(engine.set_mic_muted, False)
            loop.call_soon_threadsafe(engine.set_output_muted, False)
            logger.info("Uzak mod KAPALI (web konsolundan).")
            return {"away": False}
        if action == "interrupt":  # El Kontrolu ✊: konusmayi kes
            loop.call_soon_threadsafe(engine.interrupt_speaking)
            return {"interrupted": True}
        return {"error": "bilinmeyen"}

    return _on_web_control


async def _amain() -> None:
    settings = get_settings()
    _configure_logging(settings)
    _check_remote_safety(settings)

    loop = asyncio.get_running_loop()

    engine_observer = WebEngineObserver(confirm_timeout=settings.remote_confirm_timeout)

    audio_server: NetworkAudioServer | None = None
    audio_transport: AudioTransport | None = None
    if settings.audio_mode == "network":
        audio_server = NetworkAudioServer(
            port=settings.remote_audio_port,
            bind=settings.web_console_bind,
            token=settings.remote_audio_token,
        )
        audio_transport = NetworkAudioTransport(audio_server)
        logger.info(
            f"Ses modu: NETWORK (port {settings.remote_audio_port}) - mikrofon/"
            "hoparlor ev bilgisayarindan (remote_client) beklenecek."
        )
    else:
        logger.info("Ses modu: LOCAL - bu makinenin mikrofonu/hoparloru kullanilacak.")

    engine = BrainEngine(settings, observer=engine_observer, audio_transport=audio_transport)

    # --- WhatsApp kolu (opsiyonel, main.py ile ayni) ---
    wa_handler: WhatsAppHandler | None = None
    try:
        wa_cfg = load_whatsapp_config(settings)
        if wa_cfg.enabled:
            wa_handler = WhatsAppHandler(settings, wa_cfg, engine=engine)
            logger.info("WhatsApp kolu etkin - beyin ile birlikte calisacak.")
    except Exception as exc:  # noqa: BLE001 - WhatsApp kolu beyni engellemez
        logger.error(f"WhatsApp kolu baslatilamadi (yok sayiliyor): {exc!r}")

    # --- Telegram kolu (opsiyonel; TELEGRAM_BOT_TOKEN yoksa calismaz) ---
    tg_handler: TelegramHandler | None = TelegramHandler(settings)
    if not tg_handler.enabled:
        tg_handler = None

    # --- GUI'siz yan-thread'ler: orkestrator, web konsolu, zamanlayici ---
    # (ui/app.py:109-128 ile ayni desen - Qt gozlemcileri yerine web/web_observer.py)
    orch_observer = (
        WebOrchestratorObserver(confirm_timeout=settings.remote_confirm_timeout)
        if settings.agents_enabled
        else None
    )
    orch_worker = OrchestratorWorker(settings, orch_observer) if orch_observer else None

    web_worker = (
        WebWorker(settings, on_control=_make_on_control(engine, loop))
        if settings.web_console_enabled
        else None
    )
    scheduler_handler = (
        SchedulerHandler(
            settings, engine=engine,
            broadcaster=build_broadcaster(settings, telegram=tg_handler, whatsapp=wa_handler),
        )
        if settings.scheduler_enabled
        else None
    )

    def _request_shutdown() -> None:
        engine.request_shutdown()
        if wa_handler is not None:
            wa_handler.request_shutdown()
        if tg_handler is not None:
            tg_handler.request_shutdown()
        if scheduler_handler is not None:
            scheduler_handler.request_shutdown()

    with contextlib.suppress(NotImplementedError):  # Windows'ta desteklenmez
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _request_shutdown)

    if orch_worker is not None:
        orch_worker.start()
        orch_worker.wait_ready(5.0)
    if web_worker is not None:
        web_worker.start()
        for _ in range(20):  # ConsoleServer thread'inde kurulana kadar kisa bekleme
            if web_worker.url:
                break
            await asyncio.sleep(0.1)
        url = web_worker.url or "(baslatiliyor...)"
        if settings.web_console_token:  # token log dosyasina yazilmasin
            url = url.replace(settings.web_console_token, "***")
        logger.success(f"Web konsolu: {url}")

    try:
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(engine.run(), name="brain_engine")
            if wa_handler is not None:
                task_group.create_task(wa_handler.run(), name="whatsapp_handler")
            if tg_handler is not None:
                task_group.create_task(tg_handler.run(), name="telegram_handler")
            if scheduler_handler is not None:
                task_group.create_task(scheduler_handler.run(), name="scheduler_handler")
            if audio_server is not None:
                task_group.create_task(audio_server.run(), name="remote_audio_server")
    except* Exception as group:  # noqa: BLE001
        for exc in group.exceptions:
            logger.error(f"Ana gorev hatasi: {exc!r}")
    finally:
        _request_shutdown()
        for w in (orch_worker, web_worker):
            if w is not None:
                w.shutdown()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("Klavye kesintisi - cikiliyor.")
    except SystemExit as exc:
        logger.critical(str(exc))
        raise
    except Exception as exc:  # noqa: BLE001
        logger.critical(f"Olumcul hata: {exc!r}")
        raise


if __name__ == "__main__":
    main()
