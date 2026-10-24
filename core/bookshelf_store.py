"""Kitaplik deposu: `data/kitaplik.json` (El Kontrolu raf haritasi + kitap defteri).

Kurallar:
- Kutular aynalanmamis HAM kamera karesinde 0-1 araliginda saklanir: {x, y, w, h}.
  Ekranda ayna goruntu `x' = 1 - x - w` ile cizilir (web/static/gesture/shelf-geom.js).
- Elle duzeltilen adlar/kutular (`elle: true`) yeniden taramada ezilmez; notlar,
  alintilar ve defter her zaman korunur.
- Ayni kitap iki kez eklenmez (normalize ad + yazar).
"""

from __future__ import annotations

import contextlib
import difflib
import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

DURUMLAR = ("okunacak", "okunuyor", "bitti")
KAYNAKLAR = ("tarama", "foto", "elle", "ses", "calibre", "kamera")
_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                         "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "â": "a"})
MAX_NOTES = 500
MAX_TEXT = 4000


def normalize(text: str | None) -> str:
    """Karsilastirma anahtari: Turkce harfler sadelesir, noktalama/bosluk teklesir."""
    s = (text or "").translate(_TR_MAP).casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clamp_box(box: Any) -> dict[str, float] | None:
    """Gecerli 0-1 kutusu ya da None (tasan kutu kirpilir, bos kutu atilir)."""
    if not isinstance(box, dict):
        return None
    try:
        x, y, w, h = (float(box.get(k, 0)) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        return None
    x0, y0 = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
    x1, y1 = max(0.0, min(1.0, x + w)), max(0.0, min(1.0, y + h))
    if x1 - x0 < 0.002 or y1 - y0 < 0.002:
        return None
    return {"x": round(x0, 5), "y": round(y0, 5), "w": round(x1 - x0, 5), "h": round(y1 - y0, 5)}


def overlap_min(a: dict, b: dict) -> float:
    """Kesisim / kucuk kutunun alani (ince sirtlar parcalara bolununce IoU dusuk kalir)."""
    ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    inter = ix * iy
    small = min(a["w"] * a["h"], b["w"] * b["h"])
    return inter / small if small > 0 else 0.0


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.9
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _now() -> float:
    return round(time.time(), 3)


def _clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _new_book(ad: str | None, yazar: str | None, kaynak: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:10],
        "ad": _clean_text(ad, 200) or None,
        "yazar": _clean_text(yazar, 200) or None,
        "kutu": None,
        "elle": False,
        "durum": "okunacak",
        "sayfa": None,
        "notlar": [],
        "alintilar": [],
        "defter": None,
        "kapak": None,
        "kaynak": kaynak if kaynak in KAYNAKLAR else "elle",
        "guven": None,
        "eklendi": _now(),
        "guncel": _now(),
    }


class BookshelfStore:
    """Is parcacigi guvenli JSON deposu. Her degisiklik atomik yazilir."""

    def __init__(self, path: Path, covers_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.covers_dir = Path(covers_dir) if covers_dir else self.path.parent / "kapaklar"
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None

    # ------------------------------------------------------------ disk
    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "books": [], "raf": None, "referans": None, "tarama": None}

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        data = self._empty()
        try:
            if self.path.is_file():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("books"), list):
                    data.update(raw)
        except (OSError, ValueError) as exc:
            logger.warning(f"kitaplik.json okunamadi ({exc}); bos baslatiliyor")
        self._data = data
        return data

    def _save(self) -> None:
        data = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                json.dump(data, h, ensure_ascii=False, indent=1)
            for attempt in range(5):  # OneDrive dosyayi kisa sure kilitleyebilir
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.15 * (attempt + 1))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # ------------------------------------------------------------ okuma
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._load(), ensure_ascii=False))

    def books(self) -> list[dict[str, Any]]:
        return self.snapshot()["books"]

    def get(self, book_id: str) -> dict[str, Any] | None:
        with self._lock:
            b = self._find_id(book_id)
            return dict(b) if b else None

    def _find_id(self, book_id: str) -> dict[str, Any] | None:
        for b in self._load()["books"]:
            if b.get("id") == book_id:
                return b
        return None

    def find(self, query: str, *, min_score: float = 0.72) -> dict[str, Any] | None:
        """Ada (ya da 'ad - yazar') gore en iyi eslesen kitap."""
        q = (query or "").strip()
        if not q:
            return None
        with self._lock:
            best, best_s = None, 0.0
            for b in self._load()["books"]:
                if not b.get("ad"):
                    continue
                s = max(title_similarity(q, b["ad"]),
                        title_similarity(q, f"{b['ad']} {b.get('yazar') or ''}"))
                if s > best_s:
                    best, best_s = b, s
            return dict(best) if best is not None and best_s >= min_score else None

    def _duplicate(self, ad: str | None, yazar: str | None) -> dict[str, Any] | None:
        if not ad:
            return None
        na = normalize(ad)
        for b in self._load()["books"]:
            if b.get("ad") and normalize(b["ad"]) == na:
                if not yazar or not b.get("yazar") or title_similarity(yazar, b["yazar"]) > 0.7:
                    return b
        return None

    # ------------------------------------------------------------ yazma
    def add(self, ad: str, yazar: str | None = None, *, kaynak: str = "elle",
            kutu: dict | None = None) -> tuple[dict[str, Any], bool]:
        """Kitap ekler; ayni kitap varsa onu dondurur. -> (kitap, yeni_mi)"""
        ad = _clean_text(ad, 200)
        if not ad:
            raise ValueError("kitap adi bos")
        with self._lock:
            dup = self._duplicate(ad, yazar)
            if dup is not None:
                if yazar and not dup.get("yazar"):
                    dup["yazar"] = _clean_text(yazar, 200)
                    dup["guncel"] = _now()
                    self._save()
                return dict(dup), False
            book = _new_book(ad, yazar, kaynak)
            book["kutu"] = clamp_box(kutu)
            self._load()["books"].append(book)
            self._save()
            return dict(book), True

    def update(self, book_id: str, **fields: Any) -> dict[str, Any] | None:
        """Izinli alanlari gunceller. Ad/kutu elle degisirse `elle` isaretlenir."""
        with self._lock:
            b = self._find_id(book_id)
            if b is None:
                return None
            if "ad" in fields:
                b["ad"] = _clean_text(fields["ad"], 200) or None
                b["elle"] = True
            if "yazar" in fields:
                b["yazar"] = _clean_text(fields["yazar"], 200) or None
            if "kutu" in fields:
                b["kutu"] = clamp_box(fields["kutu"]) if fields["kutu"] else None
                b["elle"] = True
            if "durum" in fields:
                d = str(fields["durum"] or "").strip().lower()
                if d not in DURUMLAR:
                    raise ValueError(f"durum su degerlerden biri olmali: {', '.join(DURUMLAR)}")
                b["durum"] = d
            if "sayfa" in fields:
                try:
                    b["sayfa"] = max(0, int(fields["sayfa"])) if fields["sayfa"] not in (None, "") else None
                except (TypeError, ValueError) as exc:
                    raise ValueError("sayfa sayi olmali") from exc
            if "kapak" in fields:
                b["kapak"] = fields["kapak"] or None
            if "defter" in fields:
                b["defter"] = fields["defter"] if isinstance(fields["defter"], dict) else None
            b["guncel"] = _now()
            self._save()
            return dict(b)

    def link_calibre(self, book_id: str, info: dict[str, Any]) -> dict[str, Any] | None:
        """Calibre bilgisini (kimlik, formatlar, etiketler, seri, aciklama) kitaba baglar."""
        with self._lock:
            b = self._find_id(book_id)
            if b is None:
                return None
            if b.get("calibre") != info:
                b["calibre"] = info
                b["guncel"] = _now()
                self._save()
            return dict(b)

    def add_entry(self, book_id: str, metin: str, tur: str = "not",
                  sayfa: int | None = None) -> dict[str, Any] | None:
        """Not ya da alinti ekler (alintilar yalnizca kullanicinin ekledikleridir)."""
        metin = (metin or "").strip()[:MAX_TEXT]
        if not metin:
            raise ValueError("metin bos")
        key = "alintilar" if tur in ("alinti", "alıntı", "quote") else "notlar"
        with self._lock:
            b = self._find_id(book_id)
            if b is None:
                return None
            entry: dict[str, Any] = {"metin": metin, "ts": _now()}
            if sayfa is not None:
                entry["sayfa"] = sayfa
            b.setdefault(key, []).append(entry)
            b[key] = b[key][-MAX_NOTES:]
            b["guncel"] = _now()
            self._save()
            return dict(b)

    def remove_entry(self, book_id: str, tur: str, index: int) -> dict[str, Any] | None:
        key = "alintilar" if tur in ("alinti", "alıntı", "quote") else "notlar"
        with self._lock:
            b = self._find_id(book_id)
            if b is None:
                return None
            items = b.get(key) or []
            if 0 <= index < len(items):
                items.pop(index)
                b["guncel"] = _now()
                self._save()
            return dict(b)

    def delete(self, book_id: str) -> bool:
        with self._lock:
            books = self._load()["books"]
            n = len(books)
            books[:] = [b for b in books if b.get("id") != book_id]
            if len(books) != n:
                self._save()
                return True
            return False

    # ------------------------------------------------------------ raf haritasi
    def set_shelf(self, raf: dict | None = None, referans: dict | None = None) -> None:
        with self._lock:
            data = self._load()
            if raf is not None:
                data["raf"] = clamp_box(raf)
            if referans is not None:
                data["referans"] = _clean_reference(referans)
            self._save()

    def save_layout(self, items: Iterable[dict], deleted: Iterable[str] = ()) -> dict[str, Any]:
        """Kalibrasyon (K modu) kaydi: kutu ekle/tasi/adlandir/sil.

        `items`: [{id?, ad?, yazar?, kutu, link?}] - `id` varsa o kitap guncellenir; `link`
        kayitli bir kutusuz kitabin id'si ise o kitap bu kutuya yerlesir (notlari korunur).
        Kutusu silinen taramali/adsiz kitaplar tamamen silinir; adli kitaplar kutusuz kalir.
        """
        with self._lock:
            data = self._load()
            by_id = {b["id"]: b for b in data["books"]}
            for bid in deleted:
                b = by_id.get(str(bid))
                if b is None:
                    continue
                if b.get("ad") and (b.get("notlar") or b.get("alintilar") or b.get("defter")
                                    or b.get("kaynak") != "tarama"):
                    b["kutu"] = None
                    b["guncel"] = _now()
                else:
                    data["books"].remove(b)
                    by_id.pop(b["id"], None)
            for it in items:
                if not isinstance(it, dict):
                    continue
                box = clamp_box(it.get("kutu"))
                link = by_id.get(str(it.get("link") or ""))
                target = by_id.get(str(it.get("id") or ""))
                if link is not None and target is not None and link is not target:
                    # adsiz kutu kayitli bir kitaba baglandi: kutu o kitaba gecer
                    data["books"].remove(target)
                    by_id.pop(target["id"], None)
                    target = link
                elif link is not None:
                    target = link
                if target is None:
                    target = _new_book(it.get("ad"), it.get("yazar"), "elle")
                    data["books"].append(target)
                    by_id[target["id"]] = target
                if "ad" in it and (it.get("ad") or None) != target.get("ad"):
                    target["ad"] = _clean_text(it.get("ad"), 200) or None
                    target["elle"] = True
                if it.get("yazar"):
                    target["yazar"] = _clean_text(it["yazar"], 200)
                if box is not None and box != target.get("kutu"):
                    target["kutu"] = box
                    target["elle"] = True
                target["guncel"] = _now()
            self._save()
            return self.snapshot()

    def merge_scan(self, detections: Iterable[dict], *, raf: dict | None = None) -> dict[str, int]:
        """Tarama sonucunu haritaya isler. -> {taninan, belirsiz, yeni, guncellenen}"""
        dets = []
        for d in detections:
            box = clamp_box(d.get("kutu"))
            if box is None:
                continue
            ad = _clean_text(d.get("ad"), 200) or None
            dets.append({"kutu": box, "ad": ad, "yazar": _clean_text(d.get("yazar"), 200) or None,
                         "guven": d.get("guven")})
        stats = {"taninan": 0, "belirsiz": 0, "yeni": 0, "guncellenen": 0}
        with self._lock:
            data = self._load()
            books = data["books"]
            used: set[str] = set()
            for d in dets:
                stats["taninan" if d["ad"] else "belirsiz"] += 1
                # 1) ayni yerdeki mevcut kutu
                match, best = None, 0.0
                for b in books:
                    if b["id"] in used or not b.get("kutu"):
                        continue
                    ov = overlap_min(b["kutu"], d["kutu"])
                    if ov > best:
                        match, best = b, ov
                if match is not None and best >= 0.5:
                    used.add(match["id"])
                    if not match.get("elle"):
                        match["kutu"] = d["kutu"]
                        if d["ad"]:
                            match["ad"] = d["ad"]
                            match["yazar"] = d["yazar"] or match.get("yazar")
                            match["guven"] = d["guven"]
                    elif not match.get("ad") and d["ad"]:
                        match["ad"], match["yazar"] = d["ad"], d["yazar"]
                    match["guncel"] = _now()
                    stats["guncellenen"] += 1
                    continue
                # 2) kutusuz kayitli kitap (foto/elle/ses ile eklenmis) adla eslesirse yerlestir
                if d["ad"]:
                    named = None
                    for b in books:
                        if b["id"] in used or b.get("kutu") or not b.get("ad"):
                            continue
                        if title_similarity(b["ad"], d["ad"]) >= 0.85:
                            named = b
                            break
                    if named is not None:
                        named["kutu"] = d["kutu"]
                        named["guncel"] = _now()
                        used.add(named["id"])
                        stats["guncellenen"] += 1
                        continue
                # 3) yeni kutu
                nb = _new_book(d["ad"], d["yazar"], "tarama")
                nb["kutu"] = d["kutu"]
                nb["guven"] = d["guven"]
                books.append(nb)
                used.add(nb["id"])
                stats["yeni"] += 1
            if raf is not None:
                data["raf"] = clamp_box(raf)  # None: onceki bolge korunur
            data["tarama"] = {"ts": _now(), **stats}
            self._save()
        return stats

    # ------------------------------------------------------------ ozet
    def prompt_summary(self, limit: int = 40) -> str:
        """Sistem baglami icin kisa liste (yalnizca adi bilinen kitaplar)."""
        named = [b for b in self.books() if b.get("ad")]
        if not named:
            return ""
        named.sort(key=lambda b: (DURUMLAR.index(b.get("durum") or "okunacak") != 1, b.get("ad") or ""))
        lines = []
        for b in named[:limit]:
            extra = f" - {b['yazar']}" if b.get("yazar") else ""
            st = b.get("durum") or "okunacak"
            if st == "okunuyor" and b.get("sayfa"):
                st += f", s.{b['sayfa']}"
            lines.append(f"- {b['ad']}{extra} ({st})")
        more = len(named) - len(lines)
        if more > 0:
            lines.append(f"- ... ve {more} kitap daha (kitaplik_listele ile)")
        return "\n".join(lines)


def _clean_reference(ref: Any) -> dict | None:
    """Kayma referansi: {w, h, gri:[0-255 ...]} (32x24 kucuk gri resim)."""
    if not isinstance(ref, dict):
        return None
    try:
        w, h = int(ref.get("w", 0)), int(ref.get("h", 0))
        gri = [max(0, min(255, int(v))) for v in ref.get("gri", [])]
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or w * h > 4096 or len(gri) != w * h:
        return None
    return {"w": w, "h": h, "gri": gri}


_STORE: BookshelfStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> BookshelfStore:
    """Uygulama genelinde tek depo (settings.data_dir/kitaplik.json)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            from config.settings import get_settings

            s = get_settings()
            _STORE = BookshelfStore(s.data_dir / "kitaplik.json", s.data_dir / "kapaklar")
        return _STORE


def set_store(store: BookshelfStore | None) -> None:
    """Testler icin depoyu degistirir."""
    global _STORE
    with _STORE_LOCK:
        _STORE = store
