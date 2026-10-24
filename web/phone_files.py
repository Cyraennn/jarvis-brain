"""Telefon <-> PC dosya alisverisi.

  telefon -> PC : `POST /api/files/upload?name=<ad>` (govde = ham dosya) -> `~/Downloads/JARVIS/`
  PC -> telefon : `send_file_to_phone` araci dosyayi `data/phone_outbox/`'a kopyalar, veriyoluna
                  `file` olayi yazar; telefon `GET /api/files/get?name=<ad>` ile indirir.

Telefon yalnizca outbox'taki dosyalari indirebilir (yol kacisi engellenir); PC'nin geri kalani
aga acilmaz. Isimler temizlenir, ayni ad varsa "ad (2).uzanti" olur.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import BinaryIO

from config.settings import APP_DIR

PHONE_OUTBOX = APP_DIR / "data" / "phone_outbox"
PHONE_INBOX = Path.home() / "Downloads" / "JARVIS"
MAX_BYTES = 500 * 1024 * 1024
_CHUNK = 256 * 1024
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    """Yol parcalarini ve Windows'ta gecersiz karakterleri atar; bos kalirsa zaman damgali ad."""
    base = Path(str(name or "").replace("\\", "/")).name
    base = _BAD.sub("_", base).strip(" .")
    return base[:150] or f"dosya-{time.strftime('%Y%m%d-%H%M%S')}"


def unique_path(folder: Path, name: str) -> Path:
    target = folder / name
    stem, suffix = target.stem, target.suffix
    n = 2
    while target.exists():
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def save_upload(stream: BinaryIO, length: int, name: str, folder: Path | None = None) -> Path:
    """Govdeyi parca parca diske yazar (bellege almaz). Eksik gelirse yarim dosyayi siler."""
    if length <= 0:
        raise ValueError("bos dosya")
    if length > MAX_BYTES:
        raise ValueError(f"dosya cok buyuk (en fazla {MAX_BYTES // (1024 * 1024)} MB)")
    folder = folder or PHONE_INBOX
    folder.mkdir(parents=True, exist_ok=True)
    target = unique_path(folder, safe_name(name))
    left = length
    try:
        with target.open("wb") as out:
            while left > 0:
                chunk = stream.read(min(_CHUNK, left))
                if not chunk:
                    raise ValueError("baglanti yarida kesildi")
                out.write(chunk)
                left -= len(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def offer(path: str, folder: Path | None = None) -> dict:
    """PC'deki dosyayi telefona sunulmak uzere outbox'a kopyalar."""
    src = Path(str(path or "")).expanduser()
    if not src.is_file():
        return {"error": f"Dosya bulunamadi: {path}"}
    size = src.stat().st_size
    if size > MAX_BYTES:
        return {"error": "Dosya telefona gondermek icin cok buyuk (en fazla 500 MB)."}
    folder = folder or PHONE_OUTBOX
    folder.mkdir(parents=True, exist_ok=True)
    dest = unique_path(folder, safe_name(src.name))
    shutil.copy2(src, dest)
    return {"name": dest.name, "size": size, "source": src.name}


def list_outbox(folder: Path | None = None) -> list[dict]:
    folder = folder or PHONE_OUTBOX
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime} for p in files]


def outbox_file(name: str, folder: Path | None = None) -> Path | None:
    """Indirilecek dosya; outbox disina cikan ya da olmayan ad icin None."""
    folder = (folder or PHONE_OUTBOX).resolve()
    if not name or safe_name(name) != name:
        return None
    target = (folder / name).resolve()
    if target.parent != folder or not target.is_file():
        return None
    return target
