"""Sunucu loglamasi: JSON (yapilandirilmis) + boyuta gore donen dosya + journald icin stderr.

- Dosya: her satir bir JSON nesnesi (loguru `serialize=True`); `logger.bind(event=.., model=..)`
  alanlari `record.extra` altinda gorunur -> `jq 'select(.record.extra.event=="model_fallback")'`.
- stderr: insan okunur tek satir (systemd -> `journalctl -u jarvis -f`).
- CRITICAL seviyesi ayrica Telegram'a gider (tanimliysa).
- uvicorn'un standart `logging` kayitlari da loguru'ya yonlendirilir (tek format, tek dosya).
"""

from __future__ import annotations

import logging
import sys

from loguru import logger

from server.config import ServerConfig
from server.telegram import TelegramNotifier


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(cfg: ServerConfig, notifier: TelegramNotifier, level: str = "INFO") -> None:
    logger.remove()
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
            enqueue=True,
            colorize=False,
        )
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        cfg.log_path,
        level="DEBUG",
        serialize=True,          # JSON satirlari
        rotation="10 MB",
        retention=10,
        encoding="utf-8",
        enqueue=True,
    )
    logger.add(notifier.loguru_sink, level="CRITICAL", enqueue=True)

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False
    # httpx her istegi INFO'da loglar (Telegram URL'si token icerir) -> sustur
    logging.getLogger("httpx").setLevel(logging.WARNING)
