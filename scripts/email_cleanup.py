"""Gelen kutusu temizligi (tools/email_cleanup.py).

    python scripts/email_cleanup.py --dry-run --limit 200   # deneme: hicbir sey tasinmaz
    python scripts/email_cleanup.py                         # onemsizleri Cop kutusuna tasir
    python scripts/email_cleanup.py --until 07:30           # isi 07:30'a kadar agir agir yay
    python scripts/email_cleanup.py --restore data/email_cleanup/<dosya>.csv

Gercek calistirmada ozet, Obsidian gunluk notuna "Zamanli gorev (E-posta Temizligi)"
olarak yazilir; 08:30 sabah ozeti bunu otomatik okur.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger  # noqa: E402

from tools import email_cleanup  # noqa: E402


def _parse_until(value: str | None) -> datetime | None:
    """'07:30' -> bir sonraki 07:30 (gece yarisini gecse de)."""
    if not value:
        return None
    hour, minute = (int(x) for x in value.split(":"))
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def main() -> int:
    p = argparse.ArgumentParser(description="JARVIS gelen kutusu temizligi")
    p.add_argument("--dry-run", action="store_true", help="hicbir maili tasima, sadece CSV yaz")
    p.add_argument("--limit", type=int, default=None, help="en eski N maili isle")
    p.add_argument("--restore", type=Path, help="CSV'deki mailleri INBOX'a geri tasi")
    p.add_argument("--until", help="HH:MM - partiler arasinda bekleyip isi bu saate kadar yay")
    p.add_argument("--chunk", type=int, default=50, help="parti basina mail (varsayilan 50)")
    args = p.parse_args()

    from config.settings import get_settings

    logger.add(get_settings().data_dir / "email_cleanup" / "temizlik.log", encoding="utf-8")

    if args.restore:
        print(f"{email_cleanup.restore(args.restore)} mail INBOX'a geri tasindi.")
        return 0

    try:
        result = email_cleanup.run(dry_run=args.dry_run, limit=args.limit,
                                   until=_parse_until(args.until), chunk=args.chunk)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[temizlik] basarisiz")
        if not args.dry_run:
            from tools.basic_tools import remember_note

            remember_note(f"Zamanli gorev (E-posta Temizligi): gelen kutusu temizligi\n\nBASARISIZ: {exc!r}")
        return 1

    print(result["summary"])
    print(f"Ayrinti: {result['csv']}")
    if not args.dry_run:
        from tools.basic_tools import remember_note

        remember_note("Zamanli gorev (E-posta Temizligi): gelen kutusu temizligi\n\n"
                      f"{result['summary']} Geri almak icin: python scripts/email_cleanup.py "
                      f"--restore {result['csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
