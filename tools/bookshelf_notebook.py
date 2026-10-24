"""Cyraen'in kitap defteri (LLM) + Open Library kapaklari + Obsidian aynasi.

Defter bir kez yazilir ve saklanir (`book["defter"]`). Kurallar:
- Model kitabi tanimiyorsa sayfa UYDURMAZ: {"bilinmiyor": true} -> "Cyraen bu kitabi tanimiyor".
- Kitaptan birebir alinti URETMEZ (alintilar yalnizca kullanicinin ekledikleridir).
- "Benzer kitaplar" yalnizca kullanicinin kendi kitapligindan secilir.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from core.bookshelf_store import BookshelfStore, get_store, title_similarity

TextCall = Callable[[str, str], Awaitable[str]]  # (system, prompt) -> json metni

NOTEBOOK_SYSTEM = """Sen CYRAEN'sin; kullanicinin kitapligi icin kisa, dogru bir kitap defteri yazarsin.
Turkce yaz. Yalnizca JSON dondur.
KESIN KURALLAR:
1. Kitabi (ad + yazar) gercekten tanimiyorsan ya da emin degilsen SADECE {"bilinmiyor": true} dondur.
   Asla uydurma ozet, tema ya da yazar bilgisi yazma.
2. Kitaptan birebir alinti YAZMA; tirnak icinde cumle aktarma. Kendi cumlelerinle ozetle.
3. "benzerler" alanina YALNIZCA sana verilen "KULLANICININ KITAPLIGI" listesindeki adlardan,
   en fazla 4 tane, birebir ayni yazimla koy. Uygun yoksa bos liste.
JSON semasi:
{"bilinmiyor": false,
 "ozet": "3 cumle",
 "ana_fikirler": ["4-6 madde"],
 "yazar_hakkinda": "2-3 cumle",
 "temalar": ["3-6 kisa tema"],
 "neden_oku": "1-2 cumle",
 "kime_uygun": "1 cumle",
 "benzerler": ["kitapliktan ad", "..."]}"""


def _strip_quotes(text: str) -> str:
    """Model kurala ragmen uzun tirnakli alinti koyduysa onu kaldirir."""
    return re.sub(r"[\"“”«»][^\"“”«»]{60,}[\"“”«»]", "…", text or "").strip()


def _as_list(v: Any, limit: int) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [_strip_quotes(str(x))[:300] for x in v if str(x).strip()][:limit]


def clean_notebook(raw: Any, library_titles: list[str], own_title: str | None = None) -> dict[str, Any]:
    """Model cevabini semaya oturtur; benzerleri kitapliga gore suzer."""
    if not isinstance(raw, dict) or raw.get("bilinmiyor") is True or not raw.get("ozet"):
        return {"bilinmiyor": True, "ts": time.time()}
    similar = []
    for s in _as_list(raw.get("benzerler"), 8):
        best = max(library_titles, key=lambda t: title_similarity(s, t), default=None)
        if best and title_similarity(s, best) >= 0.85 and best not in similar \
                and (not own_title or title_similarity(best, own_title) < 0.9):
            similar.append(best)
    return {
        "bilinmiyor": False,
        "ozet": _strip_quotes(str(raw.get("ozet", "")))[:900],
        "ana_fikirler": _as_list(raw.get("ana_fikirler"), 6),
        "yazar_hakkinda": _strip_quotes(str(raw.get("yazar_hakkinda", "")))[:700],
        "temalar": _as_list(raw.get("temalar"), 6),
        "neden_oku": _strip_quotes(str(raw.get("neden_oku", "")))[:400],
        "kime_uygun": _strip_quotes(str(raw.get("kime_uygun", "")))[:300],
        "benzerler": similar[:4],
        "ts": time.time(),
    }


async def default_text_call(system: str, prompt: str) -> str:
    from agents.genai_util import generate_with_retry
    from config.settings import get_settings
    from tools.vision_tools import _genai

    client, types = _genai()
    resp = await generate_with_retry(
        client,
        model=get_settings().agent_model_chain,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.3,
                                           response_mime_type="application/json"),
        timeout=60.0,
    )
    return (getattr(resp, "text", None) or "").strip()


def _parse_json_obj(text: str) -> Any:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.I | re.M)
    try:
        return json.loads(t)
    except ValueError:
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except ValueError:
                return None
    return None


async def write_notebook(book_id: str, *, store: BookshelfStore | None = None,
                         text_call: TextCall | None = None, force: bool = False) -> dict[str, Any]:
    """Kitabin defterini yazar (zaten varsa ve force degilse dokunmaz)."""
    store = store or get_store()
    book = store.get(book_id)
    if book is None:
        raise ValueError("kitap bulunamadi")
    if not book.get("ad"):
        raise ValueError("kitabin adi bilinmiyor; once adlandirin")
    if book.get("defter") and not force and not book["defter"].get("bilinmiyor"):
        return book
    titles = [b["ad"] for b in store.books() if b.get("ad") and b["id"] != book_id]
    prompt = f"KITAP: {book['ad']}" + (f" - {book['yazar']}" if book.get("yazar") else "")
    cal = book.get("calibre") or {}
    if cal.get("aciklama"):  # Calibre'deki tanitim yazisi: dogru bilgi kaynagi
        prompt += f"\n\nKITAP ACIKLAMASI (kullanicinin Calibre kutuphanesinden):\n{cal['aciklama']}"
    if cal.get("etiketler"):
        prompt += "\nETIKETLER: " + ", ".join(cal["etiketler"])
    prompt += "\n\nKULLANICININ KITAPLIGI:\n" + "\n".join(f"- {t}" for t in titles[:150])
    call = text_call or default_text_call
    raw = _parse_json_obj(await call(NOTEBOOK_SYSTEM, prompt))
    defter = clean_notebook(raw, titles, book["ad"])
    updated = store.update(book_id, defter=defter) or book
    mirror_to_obsidian(updated)
    _push("kitaplik.degisti", {"neden": "defter", "id": book_id})
    return updated


# =================================================================== kapak
_UA = {"User-Agent": "CYRAEN-Kitaplik/1.0 (kisisel asistan; kapak arama)"}
_OL_SEARCH = "https://openlibrary.org/search.json"
_OL_COVER = "https://covers.openlibrary.org/b/id/{id}-M.jpg?default=false"


def fetch_cover(book_id: str, *, store: BookshelfStore | None = None, http_get=None) -> str | None:
    """Open Library'de ad + yazarla arar; kapak bulunursa data/kapaklar/<id>.jpg kaydeder."""
    store = store or get_store()
    book = store.get(book_id)
    if book is None or not book.get("ad"):
        return None
    if http_get is None:
        import httpx

        def http_get(url, **kw):  # noqa: ANN001
            return httpx.get(url, headers=_UA, timeout=12.0, follow_redirects=True, **kw)
    try:
        params = {"title": book["ad"], "limit": 5, "fields": "title,author_name,cover_i"}
        if book.get("yazar"):
            params["author"] = book["yazar"]
        def docs_of(resp) -> list:  # noqa: ANN001
            if resp.status_code != 200:
                return []
            return (resp.json() or {}).get("docs") or []

        docs = docs_of(http_get(_OL_SEARCH, params=params))
        if not docs and book.get("yazar"):  # yazar yaziminda fark olabilir: yalniz adla dene
            docs = docs_of(http_get(_OL_SEARCH, params={"title": book["ad"], "limit": 5,
                                                        "fields": "title,author_name,cover_i"}))
        docs = [d for d in docs if d.get("cover_i") and title_similarity(d.get("title"), book["ad"]) >= 0.6]
        if not docs:
            return None
        img = http_get(_OL_COVER.format(id=docs[0]["cover_i"]))
        if img.status_code != 200 or len(img.content) < 1000:
            return None
        return save_cover(book_id, img.content, store=store)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"kapak aranamadi ({book.get('ad')}): {exc!r}")
        return None


def save_cover(book_id: str, data: bytes, *, store: BookshelfStore | None = None) -> str:
    """Kapak gorselini kaydeder (kullanici yuklemesi ya da Open Library)."""
    store = store or get_store()
    if not data or data[:3] != b"\xff\xd8\xff" and data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("kapak JPEG ya da PNG olmali")
    ext = "png" if data[:4] == b"\x89PNG" else "jpg"
    store.covers_dir.mkdir(parents=True, exist_ok=True)
    name = f"{book_id}.{ext}"
    for old in store.covers_dir.glob(f"{book_id}.*"):
        old.unlink(missing_ok=True)
    (store.covers_dir / name).write_bytes(data)
    store.update(book_id, kapak=name)
    _push("kitaplik.degisti", {"neden": "kapak", "id": book_id})
    return name


def cover_path(book_id: str, *, store: BookshelfStore | None = None) -> Path | None:
    store = store or get_store()
    book = store.get(book_id)
    if not book or not book.get("kapak"):
        return None
    p = store.covers_dir / Path(book["kapak"]).name
    return p if p.is_file() else None


# =================================================================== yardimcilar
def _push(kind: str, data: dict) -> None:
    try:
        from web.event_bus import BUS

        BUS.push(kind, data)
    except Exception:  # noqa: BLE001
        pass


def mirror_to_obsidian(book: dict[str, Any]) -> None:
    """Kitabi Obsidian'da Kitaplik/<ad>.md olarak yansitir (kullanici bolumu korunur)."""
    if not book or not book.get("ad"):
        return
    try:
        from tools.obsidian_sync import write_managed_doc

        lines = [f"**Yazar:** {book.get('yazar') or '?'} · **Durum:** {book.get('durum') or 'okunacak'}"
                 + (f" · **Sayfa:** {book['sayfa']}" if book.get("sayfa") else "")]
        d = book.get("defter") or {}
        if d and not d.get("bilinmiyor"):
            lines += ["", "## Cyraen'in özeti", d.get("ozet", "")]
            if d.get("ana_fikirler"):
                lines += ["", "## Ana fikirler", *[f"- {x}" for x in d["ana_fikirler"]]]
            if d.get("yazar_hakkinda"):
                lines += ["", "## Yazar hakkında", d["yazar_hakkinda"]]
            if d.get("temalar"):
                lines += ["", "**Temalar:** " + ", ".join(d["temalar"])]
            if d.get("neden_oku"):
                lines += ["", "**Neden okumalı:** " + d["neden_oku"]]
            if d.get("kime_uygun"):
                lines += ["**Kime uygun:** " + d["kime_uygun"]]
            if d.get("benzerler"):
                lines += ["", "**Rafımdan benzerler:** " + ", ".join(f"[[{x}]]" for x in d["benzerler"])]
        if book.get("notlar"):
            lines += ["", "## Notlar", *[f"- {n['metin']}" for n in book["notlar"]]]
        if book.get("alintilar"):
            lines += ["", "## Alıntılar",
                      *[f"> {a['metin']}" + (f" (s.{a['sayfa']})" if a.get("sayfa") else "") + "\n"
                        for a in book["alintilar"]]]
        write_managed_doc(book["ad"], "\n".join(lines), "Kitaplik", tags=["kitap"], source="CYRAEN Kitaplik")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Obsidian kitap aynasi yazilamadi: {exc!r}")


def enrich_in_background(book_id: str, *, notebook: bool = True, cover: bool = True) -> None:
    """Yeni/adlandirilan kitap: kapak + defter arka planda (HTTP yaniti beklemez)."""

    def run() -> None:
        store = get_store()
        book = store.get(book_id)
        if book is None or not book.get("ad"):
            return
        if cover and not book.get("kapak"):
            fetch_cover(book_id, store=store)
        if notebook and not book.get("defter"):
            try:
                from agents.stark_team import run_sync

                run_sync(write_notebook(book_id, store=store), timeout=120)
            except Exception as exc:  # noqa: BLE001
                logger.info(f"kitap defteri yazilamadi ({book.get('ad')}): {exc!r}")
        else:
            mirror_to_obsidian(store.get(book_id) or book)

    threading.Thread(target=run, name=f"kitap-zenginlestir-{book_id}", daemon=True).start()


def run_notebook_sync(book_id: str, force: bool = False) -> dict[str, Any]:
    """Arac/HTTP thread'inden defter yazimi (bloklayan)."""
    from agents.stark_team import run_sync

    return run_sync(write_notebook(book_id, force=force), timeout=120)


__all__ = ["write_notebook", "fetch_cover", "save_cover", "cover_path", "clean_notebook",
           "mirror_to_obsidian", "enrich_in_background", "run_notebook_sync"]
