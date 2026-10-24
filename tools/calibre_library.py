"""Calibre koprusu: Calibre kutuphanesindeki e-kitaplari Jarvis'in kitapligina baglar.

- Calibre'nin `metadata.db` (SQLite) dosyasi SALT OKUNUR acilir; Calibre'ye hicbir sey yazilmaz.
  Calibre aciksa dosya kilitli olabilir: o durumda gecici kopyadan okunur.
- Kutuphane yolu: env `JARVIS_CALIBRE_LIBRARY` > Calibre ayari (%APPDATA%/calibre/global.py.json
  `library_path`) > `~/Calibre Library` > `~/Documents/Calibre Library`.
- Esitleme: her Calibre kitabi kitapliga eklenir (ayni kitap tekrar eklenmez), `calibre` alanina
  kimlik, formatlar, etiketler, seri ve aciklama yazilir; kapagi yoksa Calibre kapagi kullanilir.
  Calibre aciklamasi, Jarvis'in kitap defterini yazarken kaynak olarak verilir.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

FORMAT_ORDER = ("EPUB", "PDF", "AZW3", "MOBI", "DJVU", "CBZ", "TXT", "DOCX")
AUTO_SYNC_S = 600.0
_LOCK = threading.Lock()
_LAST_SYNC = 0.0


def find_library() -> Path | None:
    """Calibre kutuphane klasoru (icinde metadata.db olan); bulunamazsa None."""
    candidates: list[Path] = []
    env = os.getenv("JARVIS_CALIBRE_LIBRARY", "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    appdata = os.getenv("APPDATA")
    cfg_dirs = [Path(appdata) / "calibre"] if appdata else []
    cfg_dirs.append(Path.home() / ".config" / "calibre")
    for cfg in cfg_dirs:
        try:
            data = json.loads((cfg / "global.py.json").read_text(encoding="utf-8"))
            if data.get("library_path"):
                candidates.append(Path(data["library_path"]))
        except (OSError, ValueError):
            pass
    home = Path.home()
    candidates += [home / "Calibre Library", home / "Documents" / "Calibre Library",
                   home / "OneDrive" / "Calibre Library", home / "OneDrive" / "Belgeler" / "Calibre Library"]
    for c in candidates:
        if (c / "metadata.db").is_file():
            return c
    return None


def _connect(lib: Path) -> tuple[sqlite3.Connection, str | None]:
    """Salt okunur baglanti; kilitliyse gecici kopya. -> (baglanti, silinecek_kopya)"""
    db = lib / "metadata.db"
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        con.execute("SELECT 1 FROM books LIMIT 1")
        return con, None
    except sqlite3.Error:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy2(db, tmp)
        return sqlite3.connect(f"file:{Path(tmp).as_posix()}?mode=ro", uri=True), tmp


def _plain(text: str | None, limit: int = 1500) -> str:
    t = re.sub(r"<br\s*/?>|</p>", "\n", text or "", flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()[:limit]


def read_books(lib: Path | None = None) -> list[dict[str, Any]]:
    """Calibre kitaplari: [{calibre_id, ad, yazar, etiketler, seri, aciklama, formatlar, kapak, isbn}]"""
    lib = lib or find_library()
    if lib is None:
        return []
    con, tmp = _connect(lib)
    try:
        con.row_factory = sqlite3.Row
        q = """
        SELECT b.id, b.title, b.path, b.has_cover, b.series_index,
          (SELECT group_concat(a.name, ' & ') FROM books_authors_link l JOIN authors a ON a.id = l.author
             WHERE l.book = b.id) AS authors,
          (SELECT group_concat(t.name, ', ') FROM books_tags_link l JOIN tags t ON t.id = l.tag
             WHERE l.book = b.id) AS tags,
          (SELECT s.name FROM books_series_link l JOIN series s ON s.id = l.series WHERE l.book = b.id) AS series,
          (SELECT c.text FROM comments c WHERE c.book = b.id) AS comments,
          (SELECT i.val FROM identifiers i WHERE i.book = b.id AND i.type = 'isbn') AS isbn
        FROM books b ORDER BY b.title COLLATE NOCASE"""
        books = []
        for r in con.execute(q):
            folder = lib / r["path"]
            formats = {}
            for f in con.execute("SELECT format, name FROM data WHERE book = ?", (r["id"],)):
                fp = folder / f"{f['name']}.{f['format'].lower()}"
                formats[f["format"].upper()] = str(fp)
            cover = folder / "cover.jpg"
            books.append({
                "calibre_id": r["id"], "ad": r["title"], "yazar": r["authors"] or None,
                "etiketler": [t.strip() for t in (r["tags"] or "").split(",") if t.strip()],
                "seri": (f"{r['series']} #{r['series_index']:g}" if r["series"] else None),
                "aciklama": _plain(r["comments"]), "formatlar": formats,
                "kapak": str(cover) if r["has_cover"] and cover.is_file() else None,
                "isbn": r["isbn"],
            })
        return books
    finally:
        con.close()
        if tmp:
            with _suppress():
                os.unlink(tmp)


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


def sync(store=None, lib: Path | None = None) -> dict[str, Any]:  # noqa: ANN001
    """Calibre -> kitaplik esitlemesi. -> {kutuphane, toplam, eklenen, guncellenen}"""
    global _LAST_SYNC
    from core.bookshelf_store import get_store

    store = store or get_store()
    lib = lib or find_library()
    if lib is None:
        return {"error": "Calibre kutuphanesi bulunamadi. Calibre'yi kurup bir kutuphane olusturun "
                         "ya da .env'ye JARVIS_CALIBRE_LIBRARY=<klasor> yazin."}
    with _LOCK:
        try:
            books = read_books(lib)
        except (sqlite3.Error, OSError) as exc:
            return {"error": f"Calibre veritabani okunamadi: {exc}"}
        added = updated = 0
        for cb in books:
            if not cb["ad"]:
                continue
            book, new = store.add(cb["ad"], cb["yazar"], kaynak="calibre")
            info = {k: cb[k] for k in ("calibre_id", "etiketler", "seri", "aciklama", "isbn")}
            info["formatlar"] = sorted(cb["formatlar"], key=_fmt_rank)
            store.link_calibre(book["id"], info)
            if cb["kapak"] and not book.get("kapak"):
                with _suppress():
                    from tools.bookshelf_notebook import save_cover

                    save_cover(book["id"], Path(cb["kapak"]).read_bytes(), store=store)
            added += int(new)
            updated += int(not new)
        _LAST_SYNC = time.time()
    try:
        from web.event_bus import BUS

        BUS.push("kitaplik.degisti", {"neden": "calibre"})
    except Exception:  # noqa: BLE001
        pass
    logger.info(f"Calibre esitlendi: {len(books)} kitap ({added} yeni)")
    return {"kutuphane": str(lib), "toplam": len(books), "eklenen": added, "guncellenen": updated}


def maybe_auto_sync() -> None:
    """Kutuphane varsa ve son esitleme eskiyse arka planda esitler (kitaplik_listele cagirir)."""
    if time.time() - _LAST_SYNC < AUTO_SYNC_S or _LOCK.locked() or find_library() is None:
        return
    threading.Thread(target=sync, name="calibre-sync", daemon=True).start()


def _fmt_rank(fmt: str) -> int:
    return FORMAT_ORDER.index(fmt) if fmt in FORMAT_ORDER else len(FORMAT_ORDER)


def book_file(calibre_id: int, fmt: str | None = None) -> Path | None:
    """Calibre kitabinin dosyasi (tercihli format; yoksa siradaki)."""
    lib = find_library()
    if lib is None:
        return None
    for b in read_books(lib):
        if b["calibre_id"] != calibre_id:
            continue
        order = [fmt.upper()] if fmt else []
        order += sorted(b["formatlar"], key=_fmt_rank)
        for f in order:
            p = b["formatlar"].get(f)
            if p and Path(p).is_file():
                return Path(p)
    return None
