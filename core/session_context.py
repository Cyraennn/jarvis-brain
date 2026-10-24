"""Temiz bir canli oturuma verilen arka plan baglami.

Gemini Live oturumu her SIFIRDAN acildiginda (uygulama acilisi ya da devam ettirilemeyen bir
kopus) model onceki konusmayi bilmez ve tarihi tahmin eder. `build_context` sistem isteminin
sonuna eklenecek kisa bir blok uretir: simdiki tarih/saat, dunun gun sonu ozeti ve bugunku
konusmanin son satirlari. Kopan oturum `session_resumption` ile devam ettirilebiliyorsa bu blok
eklenmez (model zaten hatirliyor).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

GUNLER = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
MAX_LINES = 25
MAX_LINE_CHARS = 220      # uzun ajan ciktilari kisaltilir
MAX_CONVERSATION_CHARS = 2500
MAX_SUMMARY_CHARS = 1200

_TURN_RE = re.compile(r"^\*\*\d{2}:\d{2} · .+?:\*\* ")


def now_line(now: datetime) -> str:
    return (f"SU AN: {now:%d.%m.%Y} {GUNLER[now.weekday()]}, saat {now:%H:%M} (Turkiye saati). "
            "Bu, oturumun ACILDIGI andir; kesin saat gerektiginde get_current_datetime cagir, "
            "saati ASLA tahmin etme.")


def conversation_tail(
    conv_file: Path, max_lines: int = MAX_LINES, max_chars: int = MAX_CONVERSATION_CHARS
) -> list[str]:
    """Gunluk konusma dosyasinin son turlari ('**HH:MM · Etiket:** metin'), eskiden yeniye."""
    try:
        lines = conv_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    turns = [ln.strip() for ln in lines if _TURN_RE.match(ln.strip())]
    out: list[str] = []
    used = 0
    for turn in reversed(turns[-max_lines:]):
        if len(turn) > MAX_LINE_CHARS:
            turn = turn[:MAX_LINE_CHARS].rstrip() + " ..."
        if used + len(turn) > max_chars:
            break
        out.append(turn)
        used += len(turn)
    return out[::-1]


def build_context(settings: Any, now: datetime | None = None) -> str:
    """Sistem istemine eklenecek blok. Kasa yoksa / okunamazsa yalniz tarih satiri."""
    now = now or datetime.now().astimezone()
    parts = [now_line(now)]
    try:
        base = settings.obsidian_dir
        if base is not None:
            from core.daily_summary import read_section, summary_path

            yesterday = (now - timedelta(days=1)).date()
            path = summary_path(base, yesterday)
            recap = "\n".join(
                f"{name}: {text}" for name in ("Özet", "Açık kalanlar")
                if (text := read_section(path, name))
            )
            if recap:
                parts.append(f"DUNUN OZETI ({yesterday:%d.%m.%Y}):\n{recap[:MAX_SUMMARY_CHARS]}")
            tail = conversation_tail(base / "Konusmalar" / f"{now:%Y-%m-%d}.md")
            if tail:
                parts.append("BUGUN DAHA ONCE KONUSULANLAR (son satirlar, eskiden yeniye):\n"
                             + "\n".join(tail))
    except Exception as exc:  # noqa: BLE001 - baglam eksik olabilir, oturum yine acilir
        logger.debug(f"Oturum baglami okunamadi: {exc!r}")
    shelf = _bookshelf_part(settings)
    if shelf:
        parts.append(shelf)
    if len(parts) > 1:
        parts.append("Yukaridaki ozet ve satirlar ARKA PLAN bilgisidir: kullanici sormadikca "
                     "tekrarlama, selamlasirken okuma; yalnizca kaldiginiz yeri bilmek icin kullan.")
    return "OTURUM BAGLAMI\n" + "\n\n".join(parts)


def _bookshelf_part(settings: Any) -> str:
    """Kullanicinin kitapligindan kisa liste (asil kaynak kitaplik_listele araci)."""
    try:
        path = Path(settings.data_dir) / "kitaplik.json"
        if not path.is_file():
            return ""
        from core.bookshelf_store import BookshelfStore

        summary = BookshelfStore(path).prompt_summary(limit=40)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Kitaplik baglami okunamadi: {exc}")
        return ""
    if not summary:
        return ""
    return ("KULLANICININ KITAPLIGI (oneri yalnizca buradan; guncel liste icin kitaplik_listele):\n"
            + summary)
