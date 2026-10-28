"""El Kontrolu + Kitaplik HTTP uc noktalari (web/console_server.py buraya yonlendirir).

Hepsi kimlik dogrulamali (?key= ya da X-Jarvis-Key). Gorseller ham govdeyle gelir
(image/jpeg|png, en fazla MAX_IMAGE_BYTES), JSON govdeleri console_server sinirinda.

  GET  /api/el/durum             -> {acik: bagli /el sayfasi sayisi, kitap: acik kitap|null}
  POST /api/el/durum             -> {kitap_id|null}  sayfa acik kitabi bildirir (TTL 30 sn)
  GET  /api/el/hosgeldin.mp3     -> yuz kilidi karsilama sesi (ilk istekte uretilir, onbellekte)
  GET  /api/kitaplik             -> tum harita (kitaplar, raf, referans, son tarama)
  GET  /api/kitaplik/kapak/<id>  -> kapak gorseli
  GET  /api/kitaplik/tara/<job>  -> tarama isi durumu
  POST /api/kitaplik/tara[?demo=1] (ham jpeg) -> {job}; ilerleme BUS kitaplik.tarama
  POST /api/kitaplik/foto        (ham jpeg) -> telefon fotografindan kitap ekler
  POST /api/kitaplik/kapak?id=   (ham jpeg/png) -> kapak yukler
  POST /api/kitaplik/kaydet      -> {items, silinen, raf?, referans?} kalibrasyon kaydi
  POST /api/kitaplik/kitap       -> {islem: ekle|guncelle|not|alinti|not_sil|sil, ...}
  POST /api/kitaplik/defter      -> {id, force?} Jarvis doldursun / yeniden yaz
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from loguru import logger

from web.event_bus import BUS

MAX_IMAGE_BYTES = 15 * 1024 * 1024
OPEN_BOOK_TTL_S = 30.0


class _ElClients:
    """Bagli /el sayfalari (SSE client=el) ve sayfanin bildirdigi acik kitap."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._book: dict | None = None
        self._book_ts = 0.0

    def attach(self) -> None:
        with self._lock:
            self._count += 1
        BUS.push("el.durum", {"acik": self.count})

    def detach(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)
            if self._count == 0:
                self._book = None
        BUS.push("el.durum", {"acik": self.count})

    @property
    def count(self) -> int:
        return self._count

    @property
    def connected(self) -> bool:
        return self._count > 0

    def set_open_book(self, book: dict | None) -> None:
        with self._lock:
            self._book = book
            self._book_ts = time.time()

    def open_book(self) -> dict | None:
        """Sayfada acik kitap (sayfa 30 sn'de bir yeniler; kapaninca/kopunca None)."""
        with self._lock:
            if self._book is None or time.time() - self._book_ts > OPEN_BOOK_TTL_S:
                return None
            return dict(self._book)


EL_CLIENTS = _ElClients()


# ===================================================================== yardimci
def _qs(handler) -> dict[str, list[str]]:  # noqa: ANN001
    return parse_qs(urlparse(handler.path).query)


def _read_image(handler) -> bytes:  # noqa: ANN001
    """Ham gorsel govdesi; boyut okumadan once kontrol edilir."""
    try:
        n = int(handler.headers.get("Content-Length", 0))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        raise ValueError("gorsel govdesi bos")
    if n > MAX_IMAGE_BYTES:
        from web.console_server import _BodyTooLarge

        raise _BodyTooLarge(n)
    data = handler.rfile.read(n)
    if data[:3] != b"\xff\xd8\xff" and data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("JPEG ya da PNG bekleniyor")
    return data


def _welcome_mp3() -> Path | None:
    """Karsilama sesini ilk istekte uretir; metin+ses degisince yeni dosya (hash'li ad)."""
    from config.settings import get_settings

    s = get_settings()
    key = hashlib.sha1(f"{s.welcome_voice}|{s.welcome_text}".encode("utf-8")).hexdigest()[:10]
    folder = s.data_dir / "el"
    target = folder / f"hosgeldin_{key}.mp3"
    if target.is_file() and target.stat().st_size > 0:
        return target
    with _WELCOME_LOCK:
        if target.is_file() and target.stat().st_size > 0:
            return target
        from agents.stark_team import run_sync
        from core.tts import synthesize

        try:
            audio = run_sync(synthesize(s.welcome_text, s.welcome_voice), timeout=30)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"karsilama sesi uretilemedi: {exc!r}")
            return None
        if not audio:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(audio)
        for attempt in range(5):  # OneDrive kilidi
            try:
                tmp.replace(target)
                break
            except PermissionError:
                time.sleep(0.15 * (attempt + 1))
        for old in folder.glob("hosgeldin_*.mp3"):
            if old != target:
                old.unlink(missing_ok=True)
        return target if target.is_file() else None


_WELCOME_LOCK = threading.Lock()


def prewarm_welcome() -> None:
    """Sunucu acilirken sesi arka planda hazirlar (ag yoksa ilk istekte tekrar denenir)."""
    threading.Thread(target=_welcome_mp3, name="el-hosgeldin", daemon=True).start()


# ===================================================================== GET
def handle_get(handler, server, path: str) -> None:  # noqa: ANN001, ARG001
    from core.bookshelf_store import get_store

    if path == "/api/el/durum":
        handler._json(200, {"acik": EL_CLIENTS.count, "kitap": EL_CLIENTS.open_book()})
        return
    if path == "/api/el/hosgeldin.mp3":
        mp3 = _welcome_mp3()
        if mp3 is None:
            handler._json(503, {"error": "karsilama sesi uretilemedi (edge-tts / internet)"})
            return
        handler._raw(mp3.read_bytes(), "audio/mpeg", cache="max-age=3600")
        return
    if path == "/api/kitaplik":
        handler._json(200, get_store().snapshot())
        return
    if path.startswith("/api/kitaplik/kapak/"):
        from tools.bookshelf_notebook import cover_path

        fp = cover_path(path.rsplit("/", 1)[-1])
        if fp is None:
            handler._json(404, {"error": "kapak yok"})
            return
        ctype = "image/png" if fp.suffix == ".png" else "image/jpeg"
        handler._raw(fp.read_bytes(), ctype, cache="max-age=600")
        return
    if path.startswith("/api/kitaplik/tara/"):
        from tools.bookshelf_scan import job_status

        job = job_status(path.rsplit("/", 1)[-1])
        handler._json(200 if job else 404, job or {"error": "is bulunamadi"})
        return
    handler._json(404, {"error": "yok"})


# ===================================================================== POST
def handle_post(handler, server, path: str) -> None:  # noqa: ANN001, ARG001
    try:
        code, payload = _post(handler, path)
    except ValueError as exc:
        handler.close_connection = True
        code, payload = 400, {"error": str(exc)}
    except RuntimeError as exc:
        code, payload = 409, {"error": str(exc)}
    handler._json(code, payload)


def _post(handler, path: str) -> tuple[int, Any]:  # noqa: ANN001, C901
    from core.bookshelf_store import get_store
    from tools import bookshelf_notebook as nb

    store = get_store()
    if path == "/api/kitaplik/tara":
        jpeg = _read_image(handler)
        qs = _qs(handler)
        demo = qs.get("demo", ["0"])[0] == "1"
        region = None
        if qs.get("bolge"):
            try:
                x, y, w, h = (float(v) for v in qs["bolge"][0].split(","))
                region = {"x": x, "y": y, "w": w, "h": h}
            except ValueError:
                region = None
        if qs.get("tam", ["0"])[0] == "1":
            region = {"x": 0, "y": 0, "w": 1, "h": 1}
        from tools.bookshelf_scan import start_scan_job

        return 200, start_scan_job(jpeg, region=region, demo=demo)
    if path == "/api/kitaplik/foto":
        jpeg = _read_image(handler)
        from agents.stark_team import run_sync
        from tools.bookshelf_scan import read_photo

        try:
            found = run_sync(read_photo(jpeg), timeout=120)
        except Exception as exc:  # noqa: BLE001
            return 502, {"error": f"fotograf okunamadi: {exc}"}
        added, existing = [], []
        for item in found:
            book, new = store.add(item["ad"], item.get("yazar"), kaynak="foto")
            (added if new else existing).append(book["ad"])
            if new:
                nb.enrich_in_background(book["id"])
        BUS.push("kitaplik.degisti", {"neden": "foto"})
        return 200, {"okunan": len(found), "eklenen": added, "zaten_vardi": existing}
    if path == "/api/kitaplik/eldeki":
        jpeg = _read_image(handler)
        from agents.stark_team import run_sync
        from tools.bookshelf_scan import read_held_book

        try:
            res = run_sync(read_held_book(jpeg), timeout=90)
        except Exception as exc:  # noqa: BLE001
            return 502, {"error": f"kitap okunamadi: {exc}"}
        if not res["ad"] or res["guven"] < 0.35:
            msg = "Karede kitap görmedim." if not res["kitap_var"] else \
                "Kitabın adını okuyamadım; kapağı kameraya daha yakın ve düz tutun."
            BUS.push("kitaplik.eldeki", {"durum": "okunamadi", "mesaj": msg, **res})
            return 200, {"durum": "okunamadi", "mesaj": msg, **res}
        book, new = store.add(res["ad"], res.get("yazar"), kaynak="kamera")
        if new:
            nb.enrich_in_background(book["id"])
        out = {"durum": "eklendi" if new else "zaten_vardi", "kitap": book, **res}
        BUS.push("kitaplik.eldeki", {k: v for k, v in out.items() if k != "kitap"} | {"id": book["id"]})
        BUS.push("kitaplik.degisti", {"neden": "eldeki", "id": book["id"]})
        return 200, out
    if path == "/api/kitaplik/kapak":
        book_id = _qs(handler).get("id", [""])[0]
        if store.get(book_id) is None:
            return 404, {"error": "kitap bulunamadi"}
        return 200, {"kapak": nb.save_cover(book_id, _read_image(handler))}

    data = handler._read_body()
    if path == "/api/el/durum":
        book_id = data.get("kitap_id")
        book = store.get(str(book_id)) if book_id else None
        EL_CLIENTS.set_open_book({"id": book["id"], "ad": book.get("ad"), "sayfa": data.get("sayfa")}
                                 if book else None)
        return 200, {"status": "ok"}
    if path == "/api/kitaplik/kaydet":
        items = data.get("items") or []
        deleted = data.get("silinen") or []
        if not isinstance(items, list) or not isinstance(deleted, list):
            raise ValueError("items ve silinen liste olmali")
        before = {b["id"]: b.get("ad") for b in store.books()}
        snap = store.save_layout(items, deleted)
        if data.get("raf") is not None or data.get("referans") is not None:
            store.set_shelf(raf=data.get("raf"), referans=data.get("referans"))
        for b in snap["books"]:  # yeni adlandirilan kitaplar: kapak + defter
            if b.get("ad") and before.get(b["id"]) != b["ad"]:
                nb.enrich_in_background(b["id"])
        BUS.push("kitaplik.degisti", {"neden": "kaydet"})
        return 200, store.snapshot()
    if path == "/api/kitaplik/kitap":
        return _book_op(store, data)
    if path == "/api/kitaplik/calibre":
        from tools.calibre_library import sync

        out = sync()
        return (200 if "error" not in out else 404), out
    if path == "/api/kitaplik/defter":
        book_id = str(data.get("id", ""))
        if store.get(book_id) is None:
            return 404, {"error": "kitap bulunamadi"}
        try:
            book = nb.run_notebook_sync(book_id, force=bool(data.get("force")))
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            return 502, {"error": f"defter yazilamadi: {exc}"}
        return 200, book
    return 404, {"error": "yok"}


def _book_op(store, data: dict) -> tuple[int, Any]:  # noqa: ANN001
    from tools import bookshelf_notebook as nb

    op = str(data.get("islem", "")).strip().lower()
    if op == "ekle":
        book, new = store.add(str(data.get("ad", "")), data.get("yazar"),
                              kaynak=str(data.get("kaynak") or "elle"))
        if new:
            nb.enrich_in_background(book["id"])
        BUS.push("kitaplik.degisti", {"neden": "ekle", "id": book["id"]})
        return 200, {"kitap": book, "yeni": new}
    book_id = str(data.get("id", ""))
    if store.get(book_id) is None:
        return 404, {"error": "kitap bulunamadi"}
    if op == "guncelle":
        fields = {k: data[k] for k in ("ad", "yazar", "durum", "sayfa", "kutu") if k in data}
        before = store.get(book_id) or {}
        book = store.update(book_id, **fields)
        if book and book.get("ad") and before.get("ad") != book["ad"]:
            nb.enrich_in_background(book_id)
        else:
            nb.mirror_to_obsidian(book or {})
    elif op in ("not", "alinti"):
        sayfa = data.get("sayfa")
        book = store.add_entry(book_id, str(data.get("metin", "")), op,
                               int(sayfa) if str(sayfa or "").isdigit() else None)
        nb.mirror_to_obsidian(book or {})
    elif op == "not_sil":
        book = store.remove_entry(book_id, str(data.get("tur", "not")), int(data.get("index", -1)))
        nb.mirror_to_obsidian(book or {})
    elif op == "sil":
        store.delete(book_id)
        BUS.push("kitaplik.degisti", {"neden": "sil", "id": book_id})
        return 200, {"status": "silindi"}
    else:
        raise ValueError(f"bilinmeyen islem: {op}")
    BUS.push("kitaplik.degisti", {"neden": op, "id": book_id})
    return 200, {"kitap": book}
