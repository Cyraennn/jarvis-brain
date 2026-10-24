"""El Kontrolu + Kitaplik sesli araclari (Gemini Live -> ToolRunner).

Sayfa (`/el`) aciksa komutlar BUS olaylariyla ona gider (`el.control`, `el.gezegen`);
kapaliysa El Kontrolu uygulama penceresinde acilir. Kitaplik verisi `core.bookshelf_store`.
"""

from __future__ import annotations

import threading
from typing import Any

from core.bookshelf_store import DURUMLAR, get_store

GEZEGENLER = ("saturn", "dunya", "mars", "jupiter", "ay", "gunes")
_GEZEGEN_ADLARI = {
    "saturn": "saturn", "satürn": "saturn", "dunya": "dunya", "dünya": "dunya", "mars": "mars",
    "jupiter": "jupiter", "jüpiter": "jupiter", "ay": "ay", "gunes": "gunes", "güneş": "gunes",
}


def _bus(kind: str, data: dict) -> None:
    from web.event_bus import BUS

    BUS.push(kind, data)


def _el_open() -> bool:
    from web.el_api import EL_CLIENTS

    return EL_CLIENTS.connected


def _open_page(params: dict[str, str] | None = None) -> dict[str, Any]:
    # tool_runner'daki referans uzak (sunucu) modda istemci vekiliyle degistirilir
    import tools.tool_runner as tool_runner

    return tool_runner.open_console_app("/el", params)


# ===================================================================== El Kontrolu
def el_kontrolu_ac(demo: bool = False) -> dict[str, Any]:
    """El Kontrolu'nu acar (sayfa aciksa yeniden odaklar/etkinlestirir)."""
    if _el_open() and not demo:
        _bus("el.control", {"islem": "ac"})
        return {"status": "zaten acik", "note": "El Kontrolu etkinlestirildi."}
    out = _open_page({"el": "demo"} if demo else None)
    return {**out, "note": "Kamera izni istenirse Izin ver'e basin. Esc ile kapanir."}


def el_kontrolu_kapat() -> dict[str, Any]:
    if not _el_open():
        return {"status": "zaten kapali"}
    _bus("el.control", {"islem": "kapat"})
    return {"status": "kapatildi"}


def el_gezegen(ad: str) -> dict[str, Any]:
    """Eldeki parcacik gezegenini degistirir ('Mars yap', 'Jupiter'e cevir')."""
    key = _GEZEGEN_ADLARI.get((ad or "").strip().casefold().rstrip("'e").strip())
    if key is None:
        key = _GEZEGEN_ADLARI.get((ad or "").strip().casefold().split("'")[0])
    if key is None:
        return {"error": f"Bilinmeyen gezegen: {ad}. Secenekler: Saturn, Dunya, Mars, Jupiter, Ay, Gunes."}
    if not _el_open():
        return {"error": "El Kontrolu acik degil. Once el_kontrolu_ac."}
    _bus("el.gezegen", {"ad": key})
    return {"status": "ok", "gezegen": key,
            "note": "Elde gezegen varsa yeni haline donusur; yoksa bir sonraki cimdikte bu gelir."}


# ===================================================================== Kitaplik
def _resolve(kitap: str | None) -> tuple[dict | None, str | None]:
    """'kitap' adindan ya da El Kontrolu'nde acik kitaptan hedefi bulur."""
    store = get_store()
    if kitap and kitap.strip():
        book = store.find(kitap)
        return (book, None) if book else (None, f"Kitaplikta '{kitap}' bulunamadi.")
    from web.el_api import EL_CLIENTS

    open_book = EL_CLIENTS.open_book()
    if open_book:
        return store.get(open_book["id"]), None
    return None, "Hangi kitap? Adini soyleyin ya da El Kontrolu'nde bir kitap acin."


def _brief(book: dict) -> dict[str, Any]:
    d = book.get("defter") or {}
    return {"id": book["id"], "ad": book.get("ad"), "yazar": book.get("yazar"),
            "durum": book.get("durum"), "sayfa": book.get("sayfa"),
            "not_sayisi": len(book.get("notlar") or []), "rafta": bool(book.get("kutu")),
            "e_kitap": (book.get("calibre") or {}).get("formatlar") or None,
            "defter": "var" if d and not d.get("bilinmiyor") else ("taninmiyor" if d else "yok")}


def kitaplik_listele(durum: str = "", sorgu: str = "") -> dict[str, Any]:
    """Kullanicinin kitapligi (oneriler YALNIZCA buradan yapilir)."""
    from tools.calibre_library import maybe_auto_sync

    maybe_auto_sync()  # Calibre varsa arka planda tazele
    books = [b for b in get_store().books() if b.get("ad")]
    if durum:
        books = [b for b in books if b.get("durum") == durum.strip().lower()]
    if sorgu:
        from core.bookshelf_store import title_similarity

        books = sorted(books, key=lambda b: -max(title_similarity(sorgu, b["ad"]),
                                                  title_similarity(sorgu, b.get("yazar") or "")))[:10]
    unnamed = sum(1 for b in get_store().books() if not b.get("ad"))
    return {"toplam": len(books), "adsiz_rafta": unnamed, "kitaplar": [_brief(b) for b in books[:120]]}


def kitaplik_tara() -> dict[str, Any]:
    """Raf taramasini baslatir (kare El Kontrolu sayfasindaki kameradan alinir)."""
    if _el_open():
        _bus("el.control", {"islem": "tara"})
        return {"status": "tarama baslatildi", "note": "20-30 saniye surer; ekranda ilerleme gorunur."}
    out = _open_page({"tara": "1"})
    return {**out, "note": "El Kontrolu acildi; kamera hazir olunca tarama kendiliginden baslar."}


def kitaplik_ekle(ad: str, yazar: str = "") -> dict[str, Any]:
    from tools.bookshelf_notebook import enrich_in_background

    try:
        book, new = get_store().add(ad, yazar or None, kaynak="ses")
    except ValueError as exc:
        return {"error": str(exc)}
    if new:
        enrich_in_background(book["id"])
    _bus("kitaplik.degisti", {"neden": "ekle", "id": book["id"]})
    return {"status": "eklendi" if new else "zaten kitaplikta", "kitap": _brief(book),
            "note": "Kapak ve Cyraen'in sayfalari arka planda doluyor." if new else ""}


def kitap_adlandir(ad: str, yazar: str = "") -> dict[str, Any]:
    """El Kontrolu'nde acik (adi okunamamis) kitaba ad verir: 'bu kitabin adi Davranis'."""
    from tools.bookshelf_notebook import enrich_in_background
    from web.el_api import EL_CLIENTS

    open_book = EL_CLIENTS.open_book()
    if not open_book:
        return kitaplik_ekle(ad, yazar)  # acik kitap yok: kitapliga ekle
    store = get_store()
    fields: dict[str, Any] = {"ad": ad}
    if yazar:
        fields["yazar"] = yazar
    try:
        book = store.update(open_book["id"], **fields)
    except ValueError as exc:
        return {"error": str(exc)}
    if book is None:
        return {"error": "Acik kitap bulunamadi."}
    store.update(book["id"], defter=None)  # yeni ada gore yeniden yazilsin
    enrich_in_background(book["id"])
    _bus("kitaplik.degisti", {"neden": "adlandir", "id": book["id"]})
    return {"status": "adlandirildi", "kitap": _brief(book),
            "note": "Kapak araniyor, sayfalar birkac saniyede dolar."}


def kitap_not_ekle(metin: str, kitap: str = "", tur: str = "not", sayfa: int = 0) -> dict[str, Any]:
    """Kitaba not ya da alinti ekler. Kitap kayitli degilse once eklenir."""
    from tools.bookshelf_notebook import enrich_in_background, mirror_to_obsidian

    store = get_store()
    book, err = _resolve(kitap)
    if book is None and kitap:
        book, _ = store.add(kitap, kaynak="ses")
        enrich_in_background(book["id"])
    elif book is None:
        return {"error": err}
    try:
        updated = store.add_entry(book["id"], metin, "alinti" if tur.startswith("al") else "not",
                                  sayfa or None)
    except ValueError as exc:
        return {"error": str(exc)}
    mirror_to_obsidian(updated or book)
    _bus("kitaplik.degisti", {"neden": "not", "id": book["id"]})
    return {"status": "eklendi", "kitap": book.get("ad"), "tur": tur}


def kitap_durum(kitap: str = "", durum: str = "", sayfa: int = 0) -> dict[str, Any]:
    """Okuma durumu/sayfa: 'X'i bitirdim', 'Oblomov'da 120. sayfadayim'."""
    from tools.bookshelf_notebook import mirror_to_obsidian

    book, err = _resolve(kitap)
    if book is None:
        if not kitap:
            return {"error": err}
        book, _ = get_store().add(kitap, kaynak="ses")
    fields: dict[str, Any] = {}
    if durum:
        fields["durum"] = durum
    if sayfa:
        fields["sayfa"] = sayfa
        fields.setdefault("durum", "okunuyor")
    if not fields:
        return {"kitap": _brief(book)}
    try:
        updated = get_store().update(book["id"], **fields)
    except ValueError as exc:
        return {"error": f"{exc}. Gecerli: {', '.join(DURUMLAR)}"}
    mirror_to_obsidian(updated or book)
    _bus("kitaplik.degisti", {"neden": "durum", "id": book["id"]})
    return {"status": "guncellendi", "kitap": _brief(updated or book)}


def kitap_defter_doldur(kitap: str = "", yeniden: bool = False) -> dict[str, Any]:
    """Cyraen'in kitap defterini (ozet, ana fikirler, yazar, temalar...) yazar."""
    from tools.bookshelf_notebook import run_notebook_sync

    book, err = _resolve(kitap)
    if book is None:
        return {"error": err}
    if not book.get("ad"):
        return {"error": "Kitabin adi bilinmiyor. 'Bu kitabin adi ...' deyin."}

    def run() -> None:
        try:
            run_notebook_sync(book["id"], force=yeniden)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=run, name="kitap-defter", daemon=True).start()
    return {"status": "dolduruluyor", "kitap": book["ad"], "note": "Birkac saniye icinde sayfada gorunur."}


def kitap_ozetle(kitap: str = "") -> dict[str, Any]:
    """Kitabin Cyraen ozetini dondurur (sesli okumak icin). Defter yoksa once yazar."""
    from tools.bookshelf_notebook import run_notebook_sync

    book, err = _resolve(kitap)
    if book is None:
        return {"error": err}
    d = book.get("defter")
    if not d and book.get("ad"):
        try:
            book = run_notebook_sync(book["id"])
            d = book.get("defter")
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Ozet yazilamadi: {exc}"}
    if not d or d.get("bilinmiyor"):
        return {"kitap": book.get("ad"), "ozet": None,
                "note": "Cyraen bu kitabi tanimiyor; uydurma ozet verme, kullaniciya bunu soyle."}
    return {"kitap": book.get("ad"), "yazar": book.get("yazar"), "ozet": d.get("ozet"),
            "ana_fikirler": d.get("ana_fikirler"), "note": "Ozeti kendi sesinle kisaca oku."}


# ===================================================================== Calibre
def calibre_esitle() -> dict[str, Any]:
    """Calibre kutuphanesindeki e-kitaplari kitapliga aktarir/gunceller."""
    from tools.calibre_library import sync

    return sync()


def kitap_ac(kitap: str = "", format: str = "") -> dict[str, Any]:  # noqa: A002
    """Kitabin e-kitap dosyasini (Calibre) acar. PDF ise CYRAEN panelinde, digerleri varsayilan okuyucuda."""
    from tools.calibre_library import book_file, find_library, sync

    book, err = _resolve(kitap)
    if book is None and find_library() is not None:
        sync()  # yeni eklenmis olabilir
        book, err = _resolve(kitap)
    if book is None:
        return {"error": err}
    cal = book.get("calibre") or {}
    if not cal.get("calibre_id"):
        return {"error": f"'{book.get('ad')}' Calibre kutuphanesinde yok (yalnizca fiziksel kitap)."}
    path = book_file(int(cal["calibre_id"]), format or None)
    if path is None:
        return {"error": "Kitabin dosyasi Calibre klasorunde bulunamadi."}
    import tools.tool_runner as tool_runner  # uzak modda istemci vekili

    out = tool_runner.open_path(str(path))
    return {**(out if isinstance(out, dict) else {}), "kitap": book.get("ad"), "format": path.suffix[1:].upper()}


def kitap_tani() -> dict[str, Any]:
    """Kameraya gosterilen (elde tutulan) kitabi tanir ve kitapliga ekler."""
    if _el_open():
        _bus("el.control", {"islem": "eldeki"})
        return {"status": "kitap okunuyor",
                "note": "Kapagi kameraya duz tut; sonuc birkac saniyede ekranda. Sonucu kopru mesaji degil, "
                        "ekrandaki kart gosterir; kullaniciya 'kapagi kameraya tutun' de."}
    out = _open_page({"eldeki": "1"})
    return {**out, "note": "El Kontrolu acildi; kamera hazir olunca kitap okunacak. Kapagi kameraya tutsun."}
