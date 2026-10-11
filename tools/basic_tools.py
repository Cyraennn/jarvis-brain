"""Bagimsiz, yan etkisi az temel araclar (tarih, sistem, dosya, not).

Hem canli beyin (`ToolRunner`) hem cok-ajanli sistem bunlari paylasir.
"""

from __future__ import annotations

import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import APP_DIR

DATA_DIR = APP_DIR / "data"
NOTES_FILE = DATA_DIR / "notes.md"


def get_current_datetime() -> dict[str, Any]:
    """Gecerli tarih ve saati yerel saat dilimiyle dondurur."""
    now = datetime.now().astimezone()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "readable": now.strftime("%d.%m.%Y %H:%M:%S"),
        "timezone": str(now.tzinfo),
        "weekday": now.strftime("%A"),
    }


def get_system_status() -> dict[str, Any]:
    """Isletim sistemi, islemci ve Python surum bilgisini dondurur."""
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
        "processor": platform.processor() or "bilinmiyor",
        "cpu_count": os.cpu_count(),
        "cwd": str(Path.cwd()),
    }


def list_directory(path: str) -> dict[str, Any]:
    """Verilen dizindeki dosya ve klasorleri listeler."""
    target = Path(path).expanduser()
    if not target.exists():
        return {"error": f"Yol bulunamadi: {target}"}
    if not target.is_dir():
        return {"error": f"Bir dizin degil: {target}"}

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir())[:200]:
        try:
            is_file = child.is_file()
            entries.append(
                {
                    "name": child.name,
                    "type": "file" if is_file else "dir",
                    "size": child.stat().st_size if is_file else None,
                }
            )
        except OSError:
            continue
    return {"path": str(target), "count": len(entries), "entries": entries}


def read_text_file(path: str, max_chars: int = 4000) -> dict[str, Any]:
    """Bir metin dosyasinin icerigini okur (karakter sinirina kadar)."""
    target = Path(path).expanduser()
    if not target.is_file():
        return {"error": f"Dosya bulunamadi: {target}"}
    try:
        limit = max(1, int(max_chars))
    except (TypeError, ValueError):
        limit = 4000
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"Okuma hatasi: {exc}"}
    return {"path": str(target), "truncated": len(text) > limit, "content": text[:limit]}


def write_text_file(path: str, content: str, append: bool = False) -> dict[str, Any]:
    """Bir metin dosyasina yazar (append=True ise sonuna ekler)."""
    target = Path(path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(content or "")
    except OSError as exc:
        return {"error": f"Yazma hatasi: {exc}"}
    return {"status": "yazildi", "path": str(target), "bytes": len((content or "").encode("utf-8"))}


def remember_note(content: str) -> dict[str, Any]:
    """Kalici hafizaya zaman damgali bir not ekler."""
    note = (content or "").strip()
    if not note:
        return {"error": "Bos not kaydedilemez."}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with NOTES_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{stamp}] " + note.replace("\n", "\n  ") + "\n")

    result: dict[str, Any] = {"status": "kaydedildi", "note": note}
    try:
        from tools.obsidian_sync import append_note

        path = append_note(note)
        if path is not None:
            result["obsidian"] = str(path)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Obsidian not senkron hatasi: {exc}")
    return result


def recall_notes() -> dict[str, Any]:
    """Daha once kaydedilmis notlari (en fazla son 50) getirir.

    Obsidian vault tanimliysa oradaki gunluk notlar da birlestirilir.
    """
    lines: list[str] = []
    if NOTES_FILE.exists():
        lines = [
            line.strip()
            for line in NOTES_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    try:
        from tools.obsidian_sync import read_recent_notes

        for item in read_recent_notes(50):
            entry = f"- {item}"
            if entry not in lines:
                lines.append(entry)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Obsidian not okuma hatasi: {exc}")

    return {"count": len(lines), "notes": lines[-50:]}
