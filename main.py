"""Beyin motorunu baslatan asenkron giris noktasi.

Kullanim:
    python main.py
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from loguru import logger

from config.settings import Settings, get_settings
from agents.orchestrator import AgentOrchestrator
from core.brain_engine import BrainEngine
from core.notifications import build_broadcaster
from core.scheduler_handler import SchedulerHandler
from core.telegram_handler import TelegramHandler
from core.whatsapp_handler import WhatsAppHandler, load_whatsapp_config


def _configure_logging(settings: Settings) -> None:
    logger.remove()
    if sys.stderr is not None:  # pythonw.exe / paketli .exe altinda None olabilir
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


async def _run_orchestrator(orchestrator: AgentOrchestrator) -> None:
    """Orkestrator hatasi TaskGroup'u (ve sesli beyni) dusurmesin."""
    try:
        await orchestrator.run()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Ajan orkestratoru sonlandi (beyin calismaya devam ediyor)")


async def _amain() -> None:
    settings = get_settings()
    _configure_logging(settings)

    engine = BrainEngine(settings)

    # --- WhatsApp kolu (opsiyonel) ---
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

    # --- Zamanlayici kolu: hatirlatici/rutin + sabah ozeti + sistem sagligi ---
    # Bildirimler aktif kanallara (ses, Telegram, WhatsApp, ntfy) dagitilir.
    scheduler_handler: SchedulerHandler | None = None
    if settings.scheduler_enabled:
        broadcaster = build_broadcaster(settings, telegram=tg_handler, whatsapp=wa_handler)
        scheduler_handler = SchedulerHandler(settings, engine=engine, broadcaster=broadcaster)

    # --- Ajan orkestratoru: dispatch_to_agent + zamanli gorevler (bridge/inbox.txt) ---
    # NOT: ayni anda run_agents.py calistirma (ikisi de inbox'i isler).
    orchestrator: AgentOrchestrator | None = None
    if settings.agents_enabled:
        try:
            orchestrator = AgentOrchestrator(settings)
        except Exception as exc:  # noqa: BLE001 - ajanlar beyni engellemez
            logger.error(f"Ajan orkestratoru baslatilamadi (yok sayiliyor): {exc!r}")

    def _request_shutdown() -> None:
        engine.request_shutdown()
        if orchestrator is not None:
            orchestrator.request_shutdown()
        if wa_handler is not None:
            wa_handler.request_shutdown()
        if tg_handler is not None:
            tg_handler.request_shutdown()
        if scheduler_handler is not None:
            scheduler_handler.request_shutdown()

    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):  # Windows'ta desteklenmez
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _request_shutdown)

    if wa_handler is None and tg_handler is None and scheduler_handler is None and orchestrator is None:
        await engine.run()
        return

    # Beyin + yan kollar (WhatsApp/Telegram/zamanlayici) ayni TaskGroup icinde. Beyin biterse (ornn.
    # "kendini kapat") kollar da durdurulur; kollarin run() metotlari tum hatalari yutar.
    async def _run_engine() -> None:
        try:
            await engine.run()
        finally:
            _request_shutdown()

    try:
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(_run_engine(), name="brain_engine")
            if wa_handler is not None:
                task_group.create_task(wa_handler.run(), name="whatsapp_handler")
            if tg_handler is not None:
                task_group.create_task(tg_handler.run(), name="telegram_handler")
            if scheduler_handler is not None:
                task_group.create_task(scheduler_handler.run(), name="scheduler_handler")
            if orchestrator is not None:
                task_group.create_task(_run_orchestrator(orchestrator), name="agent_orchestrator")
    except* Exception as group:  # noqa: BLE001
        for exc in group.exceptions:
            logger.error(f"Ana gorev hatasi: {exc!r}")
    finally:
        _request_shutdown()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("Klavye kesintisi - cikiliyor.")
    except Exception as exc:  # noqa: BLE001
        logger.critical(f"Olumcul hata: {exc!r}")
        raise


if __name__ == "__main__":
    main()
