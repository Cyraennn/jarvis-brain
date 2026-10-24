"""Raf taramasi: tek kare -> ortusen parcalar -> goruntu modeli -> kitap sirti kutulari.

Akis (El Kontrolu, K modu "Kitapligi tara" ya da sesle "kitapligimi tara"):
1. Tarayici kameradan tam cozunurlukte tek JPEG kare gonderir (POST /api/kitaplik/tara).
2. Kare 3x2 = 6 ortusen parcaya bolunur ve buyutulur. Ikinci taramadan itibaren parcalar
   yalnizca raf bolgesini kapsar (sirtlar daha buyuk gorunur, daha cok ad okunur).
3. Her parca `box_2d` ([ymin, xmin, ymax, xmax], 0-1000) + ad/yazar donduren JSON istegiyle
   modele gider; ayni anda en fazla 2 istek (ucretsiz katman RPM siniri).
4. Parca koordinatlari tam kareye cevrilir, parcalar arasi tekrarlar birlestirilir,
   sonuc `core.bookshelf_store` haritasina islenir. Ilerleme BUS `kitaplik.tarama` olayidir.

Model yalnizca sirtta GERCEKTEN okudugu adi yazar; okuyamadigi sirt `ad: null` (belirsiz).
Cevrimdisi: goruntu girdisi yerel modele gidemez, tarama acik bir hatayla biter.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from loguru import logger

from core.bookshelf_store import clamp_box, get_store, overlap_min, title_similarity

# (jpeg_bytes, prompt) -> model metni
ModelCall = Callable[[bytes, str], Awaitable[str]]

TILE_COLS, TILE_ROWS = 3, 2
TILE_OVERLAP = 0.18          # komsu parcalarla ortusme (sirt kesilmesin)
TILE_TARGET_PX = 1400        # parcanin uzun kenari bu boyuta buyutulur
MAX_CONCURRENCY = 2
MIN_REGION = 0.08            # raf bolgesi bundan kucukse tam kare taranir

SCAN_PROMPT = """Bu fotograf bir kitapligin bir bolumu. Gorunen HER kitap sirtini bul.
Her sirt icin bir JSON nesnesi dondur:
  {"box_2d": [ymin, xmin, ymax, xmax], "ad": "...", "yazar": "...", "guven": 0.0-1.0}
- box_2d 0-1000 olcekli, sirtin tamamini kapsar.
- "ad": YALNIZCA sirtta gercekten okudugun kitap adi. Tahmin etme, uydurma.
  Okuyamiyorsan, harfler bulaniksa ya da emin degilsen "ad": null yaz.
- "yazar": sirtta okunuyorsa yazar, yoksa null.
- "guven": adi okuma guvenin (ad null ise 0).
- Kitap olmayan nesneleri (kutu, dergi yigini, sus) ekleme.
Yalnizca JSON dizisi dondur: [ {...}, {...} ]"""

PHOTO_PROMPT = """Bu fotograf bir kitapliktan yakin cekim. Sirtlarda ya da kapaklarda OKUYABILDIGIN
her kitabi listele. Yalnizca gercekten okudugun adlari yaz; okunamayanlari atla, uydurma.
Yalnizca JSON dizisi dondur: [{"ad": "...", "yazar": "..." ya da null}]"""


@dataclass(frozen=True)
class Tile:
    """Tam karede normalize (0-1) parca dikdortgeni."""
    x: float
    y: float
    w: float
    h: float


# =================================================================== geometri
def make_tiles(region: dict | None = None, cols: int = TILE_COLS, rows: int = TILE_ROWS,
               overlap: float = TILE_OVERLAP) -> list[Tile]:
    """Bolgeyi (varsayilan tam kare) ortusen cols x rows parcaya boler."""
    r = clamp_box(region) if region else None
    if r is None or r["w"] < MIN_REGION or r["h"] < MIN_REGION:
        r = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    else:
        # sinirdaki sirtlar kesilmesin diye bolgeyi biraz genislet
        pad_x, pad_y = r["w"] * 0.04, r["h"] * 0.04
        x0, y0 = max(0.0, r["x"] - pad_x), max(0.0, r["y"] - pad_y)
        x1, y1 = min(1.0, r["x"] + r["w"] + pad_x), min(1.0, r["y"] + r["h"] + pad_y)
        r = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    tw = r["w"] / (cols - (cols - 1) * overlap) if cols > 1 else r["w"]
    th = r["h"] / (rows - (rows - 1) * overlap) if rows > 1 else r["h"]
    tiles = []
    for j in range(rows):
        for i in range(cols):
            x = r["x"] + i * tw * (1 - overlap)
            y = r["y"] + j * th * (1 - overlap)
            tiles.append(Tile(round(x, 5), round(y, 5), round(min(tw, r["x"] + r["w"] - x), 5),
                              round(min(th, r["y"] + r["h"] - y), 5)))
    return tiles


def remap_box(box_2d: Any, tile: Tile) -> dict[str, float] | None:
    """Parca icindeki [ymin, xmin, ymax, xmax] (0-1000) -> tam kare {x,y,w,h} (0-1)."""
    if not isinstance(box_2d, (list, tuple)) or len(box_2d) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box_2d)
    except (TypeError, ValueError):
        return None
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    ymin, xmin = max(0.0, min(1000.0, ymin)), max(0.0, min(1000.0, xmin))
    ymax, xmax = max(0.0, min(1000.0, ymax)), max(0.0, min(1000.0, xmax))
    x = tile.x + xmin / 1000.0 * tile.w
    y = tile.y + ymin / 1000.0 * tile.h
    w = (xmax - xmin) / 1000.0 * tile.w
    h = (ymax - ymin) / 1000.0 * tile.h
    return clamp_box({"x": x, "y": y, "w": w, "h": h})


# =================================================================== model cevabi
def _extract_json_array(text: str) -> list:
    """Model metninden JSON dizisi (kod citi, on/son yazi, tekil nesne toleransli)."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE | re.MULTILINE).strip()
    for candidate in (t, t[t.find("["): t.rfind("]") + 1] if "[" in t else ""):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            for key in ("kitaplar", "books", "items", "sonuc"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        if isinstance(data, list):
            return data
    return []


_JUNK_TITLES = {"null", "none", "yok", "belirsiz", "unknown", "okunamadi", "okunamiyor", "?", "-"}


def _clean_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = " ".join(value.split()).strip(" \"'.,;:")
    if not v or v.casefold() in _JUNK_TITLES or len(v) > 160:
        return None
    return v


def parse_detections(text: str, tile: Tile) -> list[dict]:
    """Tek parcanin model cevabi -> [{kutu, ad, yazar, guven}] (gecersizler atlanir)."""
    out = []
    for item in _extract_json_array(text):
        if not isinstance(item, dict):
            continue
        box = remap_box(item.get("box_2d") or item.get("box"), tile)
        if box is None:
            continue
        ad = _clean_title(item.get("ad") or item.get("title"))
        try:
            guven = float(item.get("guven", item.get("confidence", 0.0)) or 0.0)
        except (TypeError, ValueError):
            guven = 0.0
        out.append({"kutu": box, "ad": ad, "yazar": _clean_title(item.get("yazar") or item.get("author")),
                    "guven": round(max(0.0, min(1.0, guven)), 3) if ad else 0.0})
    return out


def merge_detections(dets: list[dict], threshold: float = 0.6) -> list[dict]:
    """Ortusen parcalardan gelen ayni sirti teke indirir (adli/guvenli olan kazanir)."""
    ordered = sorted(dets, key=lambda d: (d["ad"] is None, -(d.get("guven") or 0.0)))
    kept: list[dict] = []
    for d in ordered:
        dup = None
        for k in kept:
            if overlap_min(k["kutu"], d["kutu"]) < threshold:
                continue
            if k["ad"] and d["ad"] and title_similarity(k["ad"], d["ad"]) < 0.6:
                continue  # ayni yerde farkli adlar: yan yana iki ince sirt olabilir
            dup = k
            break
        if dup is None:
            kept.append(dict(d))
            continue
        # birlesik kutu: iki parcaya bolunmus uzun sirt
        a, b = dup["kutu"], d["kutu"]
        x0, y0 = min(a["x"], b["x"]), min(a["y"], b["y"])
        x1, y1 = max(a["x"] + a["w"], b["x"] + b["w"]), max(a["y"] + a["h"], b["y"] + b["h"])
        dup["kutu"] = clamp_box({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}) or a
        if not dup.get("yazar") and d.get("yazar"):
            dup["yazar"] = d["yazar"]
    kept.sort(key=lambda d: (round(d["kutu"]["y"], 1), d["kutu"]["x"]))
    return kept


def shelf_region(dets: list[dict]) -> dict | None:
    """Adi okunan sirtlarin kapsadigi bolge (sonraki tarama buraya odaklanir).

    Hic ad okunamayan bir tarama (or. kamera rafa bakmiyor, elde kitap var) bolge KAYDETMEZ:
    yoksa ekranin buyuk kismi "raf" sayilir ve orada ates/gezegen kapanir.
    """
    dets = [d for d in dets if d.get("ad")]
    if len(dets) < 3:
        return None
    x0 = min(d["kutu"]["x"] for d in dets)
    y0 = min(d["kutu"]["y"] for d in dets)
    x1 = max(d["kutu"]["x"] + d["kutu"]["w"] for d in dets)
    y1 = max(d["kutu"]["y"] + d["kutu"]["h"] for d in dets)
    return clamp_box({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})


# =================================================================== goruntu
def _decode(jpeg: bytes):
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("gorsel cozulemedi (JPEG/PNG bekleniyor)")
    return img


def crop_tile(img, tile: Tile, target_px: int = TILE_TARGET_PX) -> bytes:
    """Parcayi kirpar, uzun kenari target_px olacak sekilde buyutur, JPEG dondurur."""
    import cv2

    h, w = img.shape[:2]
    x0, y0 = int(tile.x * w), int(tile.y * h)
    x1, y1 = max(x0 + 1, int((tile.x + tile.w) * w)), max(y0 + 1, int((tile.y + tile.h) * h))
    part = img[y0:y1, x0:x1]
    ph, pw = part.shape[:2]
    scale = target_px / max(ph, pw)
    if abs(scale - 1.0) > 0.05:
        interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        part = cv2.resize(part, (max(1, int(pw * scale)), max(1, int(ph * scale))), interpolation=interp)
    ok, buf = cv2.imencode(".jpg", part, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("parca kodlanamadi")
    return buf.tobytes()


def downscale(jpeg: bytes, max_px: int = 2048) -> bytes:
    import cv2

    img = _decode(jpeg)
    h, w = img.shape[:2]
    scale = max_px / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return buf.tobytes() if ok else jpeg


# =================================================================== model
async def default_model_call(image: bytes, prompt: str) -> str:
    """Gemini goruntu cagrisi (JSON cevap). Cevrimdisi/kota: istisna yukselir."""
    from agents.genai_util import generate_with_retry
    from config.settings import get_settings
    from tools.vision_tools import _genai

    client, types = _genai()
    resp = await generate_with_retry(
        client,
        model=get_settings().vision_model_chain,
        contents=[types.Part.from_bytes(data=image, mime_type="image/jpeg"), types.Part(text=prompt)],
        config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json"),
        timeout=90.0,
    )
    return (getattr(resp, "text", None) or "").strip()


ProgressFn = Callable[[dict], None]


async def scan_frame(jpeg: bytes, *, region: dict | None = None,
                     model_call: ModelCall | None = None,
                     on_progress: ProgressFn | None = None) -> dict[str, Any]:
    """Kareyi tarar. -> {kitaplar: [...], raf, parca_hatalari}"""
    call = model_call or default_model_call
    img = _decode(jpeg)
    tiles = make_tiles(region)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    found: list[dict] = []
    errors: list[str] = []
    done = 0

    async def one(idx: int, tile: Tile) -> None:
        nonlocal done
        async with sem:
            if on_progress:
                on_progress({"faz": "parca", "parca": idx, "toplam": len(tiles),
                             "tile": tile.__dict__})
            try:
                text = await call(crop_tile(img, tile), SCAN_PROMPT)
                dets = parse_detections(text, tile)
            except Exception as exc:  # noqa: BLE001 - tek parca hatasi taramayi bitirmez
                logger.warning(f"raf parcasi {idx} okunamadi: {exc!r}")
                errors.append(f"parca {idx + 1}: {type(exc).__name__}")
                dets = []
            found.extend(dets)
            done += 1
            if on_progress:
                on_progress({"faz": "bulundu", "parca": idx, "toplam": len(tiles), "bitti": done,
                             "kutular": [{"kutu": d["kutu"], "ad": d["ad"]} for d in dets]})

    await asyncio.gather(*(one(i, t) for i, t in enumerate(tiles)))
    if errors and len(errors) == len(tiles):
        raise RuntimeError("Hicbir parca okunamadi (internet/kota?). " + "; ".join(errors[:2]))
    merged = merge_detections(found)
    if not any(d["ad"] for d in merged):
        merged = []  # adsiz kutu yigini haritayi kirletmesin
    return {"kitaplar": merged, "raf": shelf_region(merged), "parca_hatalari": errors}


async def read_photo(jpeg: bytes, *, model_call: ModelCall | None = None) -> list[dict]:
    """Telefonla yakindan cekilmis raf fotografindan okunan kitap adlari (kutusuz)."""
    call = model_call or default_model_call
    text = await call(downscale(jpeg), PHOTO_PROMPT)
    out, seen = [], set()
    for item in _extract_json_array(text):
        if not isinstance(item, dict):
            continue
        ad = _clean_title(item.get("ad") or item.get("title"))
        if not ad or ad.casefold() in seen:
            continue
        seen.add(ad.casefold())
        out.append({"ad": ad, "yazar": _clean_title(item.get("yazar") or item.get("author"))})
    return out


HELD_PROMPT = """Bu bir web kamerasi karesi. Kisi kameraya bir KITAP gosteriyor (kapagi ya da sirti).
Kitabi tani: kapakta/sirtta OKUDUGUN adi ve yazari yaz. Okunan yaziyi oldugu gibi aktar; tahmin etme.
Kapak taninmis bir kitapsa (or. bilinen bir baskinin kapagi) bunu da kullanabilirsin ama emin degilsen
"ad": null yaz. Karede kitap yoksa "kitap_var": false.
Yalnizca JSON: {"kitap_var": true, "ad": "...", "yazar": "..." ya da null, "guven": 0.0-1.0,
"okunan_metin": "kapakta okudugun yazilar"}"""


async def read_held_book(jpeg: bytes, *, model_call: ModelCall | None = None) -> dict:
    """Kameraya gosterilen tek kitabi tanir -> {kitap_var, ad, yazar, guven, okunan_metin}"""
    call = model_call or default_model_call
    text = await call(downscale(jpeg, 1600), HELD_PROMPT)
    items = _extract_json_array(text)
    item = items[0] if items and isinstance(items[0], dict) else {}
    ad = _clean_title(item.get("ad") or item.get("title"))
    try:
        guven = max(0.0, min(1.0, float(item.get("guven", 0) or 0)))
    except (TypeError, ValueError):
        guven = 0.0
    return {"kitap_var": bool(item.get("kitap_var", bool(ad))), "ad": ad,
            "yazar": _clean_title(item.get("yazar") or item.get("author")),
            "guven": round(guven, 3) if ad else 0.0,
            "okunan_metin": " ".join(str(item.get("okunan_metin") or "").split())[:300]}


# =================================================================== is kuyrugu
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_ACTIVE = threading.Event()


def _push(kind: str, data: dict) -> None:
    try:
        from web.event_bus import BUS

        BUS.push(kind, data)
    except Exception:  # noqa: BLE001
        pass


def job_status(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def start_scan_job(jpeg: bytes, *, region: dict | None = None, demo: bool = False,
                   model_call: ModelCall | None = None) -> dict:
    """Taramayi arka planda baslatir, hemen {job} doner. Ayni anda tek tarama."""
    if _ACTIVE.is_set():
        raise RuntimeError("zaten bir tarama suruyor")
    store = get_store()
    if region is None and not demo:
        region = store.snapshot().get("raf")
    job_id = uuid.uuid4().hex[:8]
    job = {"job": job_id, "durum": "calisiyor", "baslangic": time.time(), "demo": demo}
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    _ACTIVE.set()

    def progress(p: dict) -> None:
        _push("kitaplik.tarama", {"job": job_id, **p})

    def run() -> None:
        from agents.stark_team import run_sync

        try:
            _push("kitaplik.tarama", {"job": job_id, "faz": "basladi", "bolge": region})
            result = run_sync(scan_frame(jpeg, region=region, model_call=model_call,
                                         on_progress=progress), timeout=600)
            books = result["kitaplar"]
            if demo:  # demo degisiklikleri kaydedilmez
                stats = {"taninan": sum(1 for b in books if b["ad"]),
                         "belirsiz": sum(1 for b in books if not b["ad"]), "yeni": 0, "guncellenen": 0}
            else:
                stats = store.merge_scan(books, raf=result["raf"])
            summary = {"faz": "bitti", **stats, "raf": result["raf"], "hatalar": result["parca_hatalari"],
                       "kitaplar": books if demo else None}
            job.update(durum="bitti", **{k: v for k, v in summary.items() if k != "faz"})
            _push("kitaplik.tarama", {"job": job_id, **summary})
            if not demo:
                _push("kitaplik.degisti", {"neden": "tarama"})
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"raf taramasi basarisiz: {exc!r}")
            job.update(durum="hata", hata=str(exc))
            _push("kitaplik.tarama", {"job": job_id, "faz": "hata", "hata": str(exc)})
        finally:
            _ACTIVE.clear()

    threading.Thread(target=run, name=f"kitaplik-tarama-{job_id}", daemon=True).start()
    return job
