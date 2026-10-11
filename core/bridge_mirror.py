"""Yan kollarin (WhatsApp, Telegram, e-posta) sesli beyne mesaj aynalamasi.

`bridge/outbox.txt`'e yazilan her satir `BrainEngine._watch_bridge_inbox` tarafindan
canli oturuma enjekte edilir; satirlar "[KAYNAK] ..." on-ekiyle yazilir.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def mirror_to_bridge(line: str, path: Path | None = None) -> None:
    """Tek satiri (bosluklar sikistirilarak) kopruye ekler; hata asla yukari tasinmaz."""
    if path is None:
        from config.settings import get_settings

        path = get_settings().bridge_outbox_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(" ".join(line.split()).strip() + "\n")
    except OSError as exc:
        logger.debug(f"kopruye yazilamadi: {exc!r}")
