"""Ulasim ve mobilite araclari (Izmir) - ESHOT durak/hat/saat, canli otobus, rota, Izmirim Kart.

Kaynaklar (Izmir Buyuksehir acik veri):
  * Durak listesi   : openfiles.izmir.bel.tr/211488/docs/eshot-otobus-duraklari.csv
  * Hat listesi     : openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hatlari.csv
  * Hareket saatleri: openfiles.izmir.bel.tr/211488/docs/eshot-otobus-hareketsaatleri.csv
    CSV'ler `data/transit/` altinda 7 gun onbelleklenir (ilk cagri ~6 MB indirir).
  * Canli otobus    : openapi.izmir.bel.tr/api/iztek/duragayaklasanotobusler/{durakId}
                      openapi.izmir.bel.tr/api/iztek/hattinyaklasanotobusleri/{hatNo}/{durakId}
    Bu servisler Bearer token ister (.env: IZMIR_OPENAPI_TOKEN); yoksa acik bir hata doner.

Izmirim Kart icin acik bir bakiye API'si yok: arac kayitli kart numarasini verir ve
resmi bakiye sayfasini tarayicida acar.

Tum fonksiyonlar senkron (ToolRunner to_thread'de calistirir) ve hata durumunda
{"error": ...} doner.
"""

from __future__ import annotations

import csv
import io
import math
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from loguru import logger

from config.settings import get_settings

OPEN_FILES = "https://openfiles.izmir.bel.tr/211488/docs"
DATASETS = {
    "stops": f"{OPEN_FILES}/eshot-otobus-duraklari.csv",
    "lines": f"{OPEN_FILES}/eshot-otobus-hatlari.csv",
    "schedule": f"{OPEN_FILES}/eshot-otobus-hareketsaatleri.csv",
}
LIVE_API = "https://openapi.izmir.bel.tr/api/iztek"
IZMIRIM_KART_URL = "https://online.izmirimkart.com.tr/giris"
CACHE_TTL_S = 7 * 24 * 3600
SERVICE_DAY_START = "04:00"  # bundan once kalkan seferler onceki gunun gece seferidir
HTTP_TIMEOUT = 10.0
DOWNLOAD_TIMEOUT = 60.0

# hareket saatleri CSV'sindeki TARIFE_ID: 1 hafta ici, 2 cumartesi, 3 pazar (kayit sayilarindan)
_DAY_TARIFF = {"hafta_ici": "1", "cumartesi": "2", "pazar": "3"}
_TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜâÂîÎ", "cgiosuCGIOSUaAiI")

_LOCK = threading.Lock()
_MEMO: dict[str, tuple[float, list[dict[str, str]]]] = {}


# ------------------------------------------------------------------ veri katmani
def _cache_dir() -> Path:
    path = get_settings().data_dir / "transit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _dataset(name: str) -> list[dict[str, str]]:
    """CSV'yi (gerekirse indirip) satir sozlukleri olarak dondurur; bellek + disk onbellegi."""
    with _LOCK:
        memo = _MEMO.get(name)
        if memo and time.time() - memo[0] < CACHE_TTL_S:
            return memo[1]
        path = _cache_dir() / f"{name}.csv"
        fresh = path.is_file() and time.time() - path.stat().st_mtime < CACHE_TTL_S
        if not fresh:
            try:
                resp = httpx.get(DATASETS[name], timeout=DOWNLOAD_TIMEOUT, follow_redirects=True)
                resp.raise_for_status()
                path.write_bytes(resp.content)
                logger.info(f"ESHOT verisi guncellendi: {name} ({len(resp.content) // 1024} KB)")
            except httpx.HTTPError as exc:
                if not path.is_file():
                    raise RuntimeError(f"ESHOT {name} verisi indirilemedi: {exc}") from exc
                logger.warning(f"ESHOT {name} guncellenemedi, eski onbellek kullaniliyor: {exc}")
        rows = list(csv.DictReader(io.StringIO(_decode(path.read_bytes())), delimiter=";"))
        _MEMO[name] = (time.time(), rows)
        return rows


def _norm(text: str) -> str:
    return " ".join(str(text or "").translate(_TR_ASCII).lower().split())


def _stop_view(row: dict[str, str], distance_m: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "stop_id": row.get("DURAK_ID", ""),
        "name": row.get("DURAK_ADI", ""),
        "lat": _to_float(row.get("ENLEM")),
        "lon": _to_float(row.get("BOYLAM")),
        "lines": [l for l in (row.get("DURAKTAN_GECEN_HATLAR") or "").split("-") if l],
    }
    if distance_m is not None:
        out["distance_m"] = int(round(distance_m))
    return out


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_stops(rows: list[dict[str, str]], lat: float, lon: float,
                  radius_m: float, limit: int) -> list[dict[str, Any]]:
    found = []
    for row in rows:
        slat, slon = _to_float(row.get("ENLEM")), _to_float(row.get("BOYLAM"))
        if slat is None or slon is None:
            continue
        d = haversine_m(lat, lon, slat, slon)
        if d <= radius_m:
            found.append((d, row))
    found.sort(key=lambda t: t[0])
    return [_stop_view(row, d) for d, row in found[:limit]]


def _guard(name: str, exc: BaseException) -> dict[str, Any]:
    logger.warning(f"Ulasim araci {name} hatasi: {exc!r}")
    return {"error": f"{name} basarisiz: {str(exc)[:200]}"}


# ------------------------------------------------------------------ ESHOT araclari
def eshot_find_stop(query: str, limit: int = 8) -> dict[str, Any]:
    """ESHOT duraklarini adiyla arar (orn. 'Konak', 'Bornova Metro'). Durak ID, konum ve gecen hatlari doner."""
    q = _norm(query)
    if not q:
        return {"error": "'query' bos olamaz."}
    try:
        rows = _dataset("stops")
    except Exception as exc:  # noqa: BLE001
        return _guard("eshot_find_stop", exc)
    exact = [r for r in rows if _norm(r.get("DURAK_ADI", "")) == q]
    partial = [r for r in rows if q in _norm(r.get("DURAK_ADI", "")) and r not in exact]
    hits = (exact + partial)[: max(1, int(limit))]
    return {"query": query, "count": len(hits), "stops": [_stop_view(r) for r in hits]}


def eshot_nearby_stops(lat: float, lon: float, radius_m: int = 500, limit: int = 8) -> dict[str, Any]:
    """Verilen koordinata (enlem, boylam) en yakin ESHOT duraklarini mesafeye gore listeler."""
    try:
        rows = _dataset("stops")
        stops = nearest_stops(rows, float(lat), float(lon), float(radius_m), max(1, int(limit)))
    except Exception as exc:  # noqa: BLE001
        return _guard("eshot_nearby_stops", exc)
    return {"count": len(stops), "radius_m": int(radius_m), "stops": stops}


def _day_key(day: str) -> str:
    d = _norm(day)
    if d in _DAY_TARIFF:
        return d
    if d.startswith("cumartesi"):
        return "cumartesi"
    if d.startswith(("pazar", "tatil")) and not d.startswith("pazartesi"):
        return "pazar"
    if d:
        return "hafta_ici"
    wd = datetime.now().weekday()
    return "cumartesi" if wd == 5 else "pazar" if wd == 6 else "hafta_ici"


def eshot_line_info(line_no: str, day: str = "", next_count: int = 5) -> dict[str, Any]:
    """ESHOT hattinin adi/guzergahi ve hareket saatleri: baslangic ve bitisten bir sonraki kalkislar.
    day: bos (bugun) | hafta_ici | cumartesi | pazar."""
    line = str(line_no or "").strip()
    if not line:
        return {"error": "'line_no' zorunlu."}
    try:
        info = next((r for r in _dataset("lines") if r.get("HAT_NO", "").strip() == line), None)
        schedule = [r for r in _dataset("schedule") if r.get("HAT_NO", "").strip() == line]
    except Exception as exc:  # noqa: BLE001
        return _guard("eshot_line_info", exc)
    if info is None and not schedule:
        return {"error": f"{line} numarali ESHOT hatti bulunamadi."}

    key = _day_key(day)
    tariff = _DAY_TARIFF[key]
    today = [r for r in schedule if r.get("TARIFE_ID") == tariff]
    now = datetime.now().strftime("%H:%M") if not day else "00:00"
    n = max(1, int(next_count))

    def service_times(col: str) -> list[str]:
        # sefer gunu sirasi: gece yarisindan sonraki seferler (00:00-03:59) gunun SONUNA
        raw = {(r.get(col) or "").strip() for r in today if (r.get(col) or "").strip()}
        return sorted(raw, key=lambda t: (t < SERVICE_DAY_START, t))

    def upcoming(col: str) -> list[str]:
        if day:  # belirli bir gun soruldu -> o gunun bastan seferleri
            return service_times(col)[:n]
        after_midnight = now < SERVICE_DAY_START
        return [t for t in service_times(col)
                if (t < SERVICE_DAY_START, t) >= (after_midnight, now)][:n]

    out: dict[str, Any] = {"line_no": line, "day": key}
    if info:
        out.update({
            "name": info.get("HAT_ADI", ""),
            "route": info.get("GUZERGAH_ACIKLAMA", ""),
            "start": info.get("HAT_BASLANGIC", ""),
            "end": info.get("HAT_BITIS", ""),
            "note": info.get("ACIKLAMA", ""),
        })
    out["next_from_start"] = upcoming("GIDIS_SAATI")   # simdiden sonraki kalkislar
    out["next_from_end"] = upcoming("DONUS_SAATI")
    for col, key in (("GIDIS_SAATI", "start"), ("DONUS_SAATI", "end")):
        times = service_times(col)
        if times:  # gunun ILK ve SON seferi ("ilk kacta kalkiyor" sorulari icin)
            out[f"first_from_{key}"], out[f"last_from_{key}"] = times[0], times[-1]
    out["daily_trips"] = len(today)
    if not today:
        out["warning"] = "Bu gun tipi icin sefer bulunamadi."
    return out


def eshot_approaching_buses(stop_id: str, line_no: str = "") -> dict[str, Any]:
    """Bir duraga yaklasan ESHOT otobuslerini (canli) getirir; line_no verilirse yalnizca o hat.
    stop_id eshot_find_stop / eshot_nearby_stops ciktisindan alinir."""
    stop = str(stop_id or "").strip()
    if not stop.isdigit():
        return {"error": "Gecerli bir 'stop_id' (sayi) gerekli - once eshot_find_stop ile bulun."}
    token = get_settings().izmir_openapi_token
    if not token:
        return {"error": "Canli otobus servisi Izmir acik API token'i istiyor (.env: "
                         "IZMIR_OPENAPI_TOKEN). Token yoksa eshot_line_info ile tarife saatlerine bakin."}
    line = str(line_no or "").strip()
    url = (f"{LIVE_API}/hattinyaklasanotobusleri/{line}/{stop}" if line
           else f"{LIVE_API}/duragayaklasanotobusler/{stop}")
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        return _guard("eshot_approaching_buses", exc)
    if resp.status_code == 401:
        return {"error": "Izmir acik API token'i gecersiz/suresi dolmus (HTTP 401)."}
    if resp.status_code == 204 or not resp.content:
        return {"stop_id": stop, "count": 0, "buses": [], "note": "Su an yaklasan otobus yok."}
    if resp.status_code != 200:
        return {"error": f"Canli otobus servisi HTTP {resp.status_code} dondu."}
    try:
        data = resp.json()
    except ValueError:
        return {"error": "Canli otobus servisi gecersiz yanit dondu."}
    buses = data if isinstance(data, list) else data.get("result") or data.get("data") or [data]
    return {"stop_id": stop, "line_no": line or None, "count": len(buses), "buses": buses[:15]}


def plan_route(origin: str, destination: str, open_browser: bool = True) -> dict[str, Any]:
    """Iki nokta arasinda toplu tasima rotasi: Google Haritalar'i (transit modu) acar ve varis
    noktasina yakin ESHOT duraklarini onerir. origin bos ise mevcut konum kullanilir."""
    destination = (destination or "").strip()
    if not destination:
        return {"error": "'destination' zorunlu."}
    origin = (origin or "").strip()
    suffix = ", Izmir"
    url = (
        "https://www.google.com/maps/dir/?api=1&travelmode=transit"
        f"&destination={quote_plus(destination + suffix)}"
        + (f"&origin={quote_plus(origin + suffix)}" if origin else "")
    )
    opened = False
    if open_browser:
        try:
            opened = bool(webbrowser.open(url))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"tarayici acilamadi: {exc!r}")
    stops = eshot_find_stop(destination, limit=3)
    out: dict[str, Any] = {
        "origin": origin or "(mevcut konum)",
        "destination": destination,
        "maps_url": url,
        "opened_in_browser": opened,
        "destination_stops": stops.get("stops", []) if "error" not in stops else [],
    }
    if out["destination_stops"]:
        out["hint"] = ("Varis duragindan gecen hatlarin saatleri icin eshot_line_info, "
                       "canli konum icin eshot_approaching_buses kullan.")
    return out


def izmirim_kart_balance(open_browser: bool = True) -> dict[str, Any]:
    """Izmirim Kart bakiye sorgusu: kayitli kart numarasini verir ve resmi bakiye sayfasini acar
    (acik bir bakiye API'si olmadigindan bakiye otomatik okunamaz)."""
    card = get_settings().izmirim_kart_no
    opened = False
    if open_browser:
        try:
            opened = bool(webbrowser.open(IZMIRIM_KART_URL))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"tarayici acilamadi: {exc!r}")
    out: dict[str, Any] = {
        "url": IZMIRIM_KART_URL,
        "opened_in_browser": opened,
        "note": "Bakiye otomatik okunamiyor; sayfada kart numarasiyla sorgulayin. "
                "Alternatif: duraklardaki dolum makineleri veya Akbank Mobil.",
    }
    if card:
        out["card_no"] = card
    else:
        out["hint"] = "Kart numarasini .env'e IZMIRIM_KART_NO=... olarak kaydedebilirsiniz."
    return out
