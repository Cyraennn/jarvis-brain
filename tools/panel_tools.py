"""Icerik paneli araclari: video, Wikipedia, yerel belge, web sitesi, Spotify karti, haberler,
piyasa grafigi, 3B Izmir haritasi, hava durumu ve bilgi karti JARVIS arayuzunun ICINDE acilir (ayri tarayici
penceresi yerine).

Model kimlik, adres ya da dosya yolu UYDURAMAZ: yalnizca sorgu/ad verir; video kimligini,
sayfa basligini ve dosya yolunu buradaki fonksiyonlar bulur ve dogrular. Dogrulanan icerik
sonuc sozlugunde "panel" anahtariyla doner; `ToolRunner` onu arayuze iletir ve modele giden
yanittan cikarir. Dogrulanamayan istek {"error": ...} doner, panel acilmaz. Tek istisna
`show_info`: orada govdeyi model yazar (bkz. fonksiyon).

Qt'ye bagimli degildir (arayuzsuz modda ve testlerde de calisir).
"""

from __future__ import annotations

import os
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse
from xml.etree import ElementTree

import httpx
from loguru import logger

from tools.app_launcher import resolve_url
from tools.spotify_tool import spotify_enabled, spotify_playback_state

# Wikimedia, iletisim adresi (URL) icermeyen User-Agent'i 403 ile reddediyor (w.wiki/4wJS).
_UA = {"User-Agent": "JARVIS-Brain/1.0 (https://github.com/Jarvisnn/jarvis-brain; kisisel masaustu asistani)"}
_TIMEOUT = 10.0

# ------------------------------------------------------------------ video
_VIDEO_ID = re.compile(r"^[\w-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
             "youtube-nocookie.com", "www.youtube-nocookie.com"}
_MAX_CANDIDATES = 6


def video_id_from(text: str) -> str | None:
    """Bir YouTube BAGLANTISINDAN video kimligini ayiklar. Duz metin kimlik sayilmaz
    ("galatasaray" da 11 karakter): model kimlik yazarak dogrulamayi atlayamasin."""
    text = (text or "").strip()
    if "://" not in text:
        text = "https://" + text if text.lower().startswith(("youtu.be/", "youtube.com/", "www.youtube.com/",
                                                             "m.youtube.com/")) else text
    try:
        u = urlparse(text)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    vid = ""
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in _YT_HOSTS:
        parts = [p for p in u.path.split("/") if p]
        if parts[:1] == ["watch"]:
            vid = (parse_qs(u.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            vid = parts[1]
    return vid if _VIDEO_ID.match(vid) else None


def _oembed(video_id: str) -> tuple[str, dict[str, Any]]:
    """YouTube'a sorar: ("ok", {title, author_name}) | ("blocked", {}) gomme kapali | ("missing", {})."""
    watch = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r = httpx.get("https://www.youtube.com/oembed", params={"url": watch, "format": "json"},
                      headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.debug(f"oembed erisilemedi [{video_id}]: {exc!r}")
        return "unreachable", {}
    if r.status_code == 200:
        try:
            return "ok", r.json()
        except ValueError:
            return "missing", {}
    return ("blocked" if r.status_code in (401, 403) else "missing"), {}


def _search_video_ids(query: str) -> list[str]:
    """Anahtarsiz YouTube aramasi: once `ddgs`, sonuc yoksa YouTube sonuc sayfasi."""
    ids: list[str] = []
    try:
        from ddgs import DDGS

        for r in DDGS().videos(query, region="tr-tr", max_results=12):
            vid = video_id_from(str(r.get("content", "")))
            if vid and vid not in ids:
                ids.append(vid)
    except Exception as exc:  # noqa: BLE001 - arama yedegine dus
        logger.debug(f"ddgs video aramasi basarisiz: {exc!r}")
    if not ids:
        try:
            r = httpx.get("https://www.youtube.com/results", params={"search_query": query},
                          headers={**_UA, "Accept-Language": "tr"}, timeout=_TIMEOUT, follow_redirects=True)
            for vid in re.findall(r'"videoId":"([\w-]{11})"', r.text):
                if vid not in ids:
                    ids.append(vid)
        except httpx.HTTPError as exc:
            logger.debug(f"youtube sonuc sayfasi alinamadi: {exc!r}")
    return ids[:_MAX_CANDIDATES]


def show_video(query: str) -> dict[str, Any]:
    """Bir YouTube videosunu arar (ya da verilen baglantiyi) dogrular ve JARVIS panelinde oynatir."""
    query = (query or "").strip()
    if not query:
        return {"error": "'query' zorunlu: aranacak video ya da YouTube baglantisi."}
    direct = video_id_from(query)
    candidates = [direct] if direct else _search_video_ids(query)
    if not candidates:
        return {"error": f"'{query}' icin video bulunamadi. Uydurma; bulamadigini soyle."}
    blocked: dict[str, Any] | None = None
    unreachable = False
    for vid in candidates:
        status, meta = _oembed(vid)
        if status == "ok":
            title = str(meta.get("title") or "Video")
            channel = str(meta.get("author_name") or "")
            return {
                "status": "video JARVIS panelinde acildi",
                "title": title,
                "channel": channel,
                "panel": {"kind": "video", "video_id": vid, "title": title, "subtitle": channel,
                          "url": f"https://www.youtube.com/watch?v={vid}"},
            }
        if status == "blocked" and blocked is None:
            blocked = {"video_id": vid}
        unreachable = unreachable or status == "unreachable"
    if blocked:
        return {"error": "Bulunan video sahibi tarafindan baska yerde oynatmaya kapatilmis; "
                         "panelde acilamiyor. Kullaniciya soyle, istersen open_website ile YouTube'da ac.",
                "url": f"https://www.youtube.com/watch?v={blocked['video_id']}"}
    if unreachable:
        return {"error": "YouTube'a ulasilamadi; video dogrulanamadi ve acilmadi."}
    return {"error": f"'{query}' icin oynatilabilir video dogrulanamadi. Uydurma; bulamadigini soyle."}


# ------------------------------------------------------------------ wikipedia
def _wiki_summary(lang: str, title: str) -> dict[str, Any] | None:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}"
    r = httpx.get(url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
    if r.status_code != 200:
        return None
    data = r.json()
    return data if data.get("title") and data.get("type") != "https://mediawiki.org/wiki/HyperSwitch/errors/not_found" else None


def _wiki_search(lang: str, query: str) -> str | None:
    r = httpx.get(f"https://{lang}.wikipedia.org/w/api.php",
                  params={"action": "opensearch", "search": query, "limit": 1, "namespace": 0, "format": "json"},
                  headers=_UA, timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    data = r.json()
    titles = data[1] if isinstance(data, list) and len(data) > 1 else []
    return str(titles[0]) if titles else None


def show_wikipedia(title: str) -> dict[str, Any]:
    """Wikipedia sayfasini (Turkce, yoksa Ingilizce) bulur, JARVIS panelinde acar ve ozetini doner."""
    title = (title or "").strip()
    if not title:
        return {"error": "'title' zorunlu."}
    try:
        for lang in ("tr", "en"):
            data = _wiki_summary(lang, title)
            if data is None:
                found = _wiki_search(lang, title)
                data = _wiki_summary(lang, found) if found else None
            if data is None:
                continue
            urls = data.get("content_urls") or {}
            page = ((urls.get("mobile") or {}).get("page") or (urls.get("desktop") or {}).get("page") or "")
            host = (urlparse(page).hostname or "").lower()
            if not host.endswith(".wikipedia.org"):
                continue
            real = str(data["title"])
            out: dict[str, Any] = {
                "status": "Wikipedia sayfasi JARVIS panelinde acildi",
                "title": real,
                "language": lang,
                "description": data.get("description") or "",
                "summary": data.get("extract") or "",
                "panel": {"kind": "wiki", "url": page, "title": real,
                          "subtitle": f"Wikipedia · {lang.upper()}"},
            }
            if data.get("type") == "disambiguation":
                out["note"] = "Bu bir anlam ayrimi sayfasi; kullaniciya hangisini kastettigini sor."
            return out
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"Wikipedia'ya ulasilamadi ({type(exc).__name__}). Bu konuda bilgi uydurma."}
    return {"error": f"Wikipedia'da '{title}' bulunamadi. Uydurma; bulamadigini soyle."}


# ------------------------------------------------------------------ yerel belge
DOC_TYPES: dict[str, str] = {".pdf": "pdf", ".txt": "metin", ".md": "metin"}
MAX_DOC_BYTES = 50 * 1024 * 1024
_MAX_DEPTH = 4
_MAX_ENTRIES = 40_000
_SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "appdata", "dist", "build"}
_NOISE = {"pdf", "txt", "md", "ac", "goster"}
_NOISE_PREFIX = ("belge", "dosya")   # belgesi, belgesini, dosyayi ... (dolgu kelimeler)
_TR = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _fold(s: str) -> str:
    s = (s or "").replace("İ", "i").replace("I", "i").lower().translate(_TR)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def doc_roots() -> list[Path]:
    """Belge aranan / acilmasina izin verilen klasorler. `.env` JARVIS_DOCS_DIRS (`;` ile ayrilir);
    bossa Belgeler, Masaustu ve Indirilenler (OneDrive'a tasinmis olanlar dahil)."""
    raw = ""
    try:
        from config.settings import get_settings

        raw = get_settings().docs_dirs
    except Exception:  # noqa: BLE001 - ayarlar yuklenemese de varsayilanlarla calis
        raw = os.getenv("JARVIS_DOCS_DIRS", "")
    if raw.strip():
        candidates = [Path(p.strip()).expanduser() for p in raw.split(";") if p.strip()]
    else:
        home = Path.home()
        bases = [home] + ([Path(os.environ["OneDrive"])] if os.environ.get("OneDrive") else [])
        names = ("Documents", "Belgeler", "Desktop", "Masaüstü", "Downloads", "İndirilenler")
        candidates = [b / n for b in bases for n in names]
    roots: list[Path] = []
    for c in candidates:
        try:
            real = c.resolve(strict=True)
        except OSError:
            continue
        if real.is_dir() and real not in roots:
            roots.append(real)
    return roots


def _check_doc(path: Path, roots: list[Path]) -> tuple[Path | None, str]:
    """Dosya gercekten var mi, turu destekleniyor mu, izinli klasorlerin icinde mi."""
    try:
        real = path.expanduser().resolve(strict=True)
    except OSError:
        return None, "Dosya bulunamadi."
    if not real.is_file():
        return None, "Bu bir dosya degil."
    if real.suffix.lower() not in DOC_TYPES:
        return None, f"Bu dosya turu panelde acilamaz ({real.suffix or 'uzantisiz'}). Desteklenen: pdf, txt, md."
    if not any(real.is_relative_to(r) for r in roots):
        return None, ("Dosya belge klasorlerinin disinda. Panelde acmak icin klasoru .env JARVIS_DOCS_DIRS'e ekleyin; "
                      "ya da open_path ile varsayilan uygulamada acin.")
    size = real.stat().st_size
    if not size or size > MAX_DOC_BYTES:
        return None, "Dosya bos ya da panel icin fazla buyuk (50 MB siniri)."
    return real, ""


def _find_docs(words: list[str], roots: list[Path]) -> list[Path]:
    hits: list[tuple[int, float, Path]] = []
    seen = 0

    def walk(folder: Path, depth: int) -> None:
        nonlocal seen
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        for e in entries:
            seen += 1
            if seen > _MAX_ENTRIES:
                return
            name = e.name
            if name.startswith((".", "$", "~")):
                continue
            try:
                if e.is_symlink():
                    continue   # klasorun disini gosteren baglar izlenmez
                if e.is_dir():
                    if depth < _MAX_DEPTH and name.lower() not in _SKIP_DIRS:
                        walk(Path(e.path), depth + 1)
                    continue
                if os.path.splitext(name)[1].lower() not in DOC_TYPES:
                    continue
                folded = _fold(os.path.splitext(name)[0])
                if all(w in folded for w in words):
                    exact = 0 if folded == " ".join(words) else 1
                    hits.append((exact, -e.stat().st_mtime, Path(e.path)))
            except OSError:
                continue

    for root in roots:
        walk(root, 0)
    hits.sort(key=lambda h: (h[0], h[1]))
    return [h[2] for h in hits]


def _doc_result(real: Path) -> dict[str, Any]:
    kind = DOC_TYPES[real.suffix.lower()]
    return {
        "status": "belge JARVIS panelinde acildi",
        "name": real.name,
        "type": kind,
        "note": "Belgenin icerigini OKUMADIN; icerik hakkinda tahmin yurutme (ozet icin summarize_document).",
        "panel": {"kind": "doc", "path": str(real), "doc_type": kind, "title": real.name,
                  "subtitle": real.parent.name},
    }


def show_document(query: str) -> dict[str, Any]:
    """Yerel bir belgeyi (PDF, .txt, .md) dosya adiyla ya da tam yoluyla bulur ve JARVIS panelinde acar."""
    query = (query or "").strip().strip('"')
    if not query:
        return {"error": "'query' zorunlu: dosya adi ya da tam yol."}
    roots = doc_roots()
    if not roots:
        return {"error": "Belge klasoru bulunamadi (.env JARVIS_DOCS_DIRS)."}

    looks_like_path = bool(re.match(r"^[a-zA-Z]:[\\/]", query)) or query.startswith(("/", "\\", "~"))
    if looks_like_path:
        real, why = _check_doc(Path(query), roots)
        return _doc_result(real) if real else {"error": why}

    words = [w for w in _fold(query).split()
             if len(w) > 1 and w not in _NOISE and not w.startswith(_NOISE_PREFIX)]
    if not words:
        return {"error": "Hangi belge? Dosya adindan bir kelime ver."}
    checked = [r for r in (_check_doc(p, roots)[0] for p in _find_docs(words, roots)[:20]) if r]
    if not checked:
        return {"error": f"'{query}' adinda belge bulunamadi. Uydurma; bulamadigini soyle."}
    exact = [p for p in checked if _fold(p.stem) == " ".join(words)]
    if len(checked) == 1 or len(exact) == 1:
        return _doc_result(exact[0] if len(exact) == 1 else checked[0])
    return {
        "status": "birden fazla belge uyuyor; panel ACILMADI",
        "matches": [{"name": p.name, "folder": p.parent.name, "path": str(p)} for p in checked[:8]],
        "note": "Adlarini sayip hangisini istedigini sor; sonra secilenin 'path' degeriyle show_document'i yeniden cagir.",
    }


# ------------------------------------------------------------------ web sitesi
def show_website(target: str) -> dict[str, Any]:
    """Bir web sitesini (URL, alan adi, kisayol ya da arama) JARVIS panelinde acar."""
    target = (target or "").strip()
    if not target:
        return {"error": "Adres bos."}
    # http(s) disindaki semalar (file:, javascript:, data: ...) panelde acilmaz; "localhost:8770" sema degildir
    if re.match(r"^[a-zA-Z][\w+.-]*:(?!\d)", target) and not target.lower().startswith(("http://", "https://")):
        return {"error": "Panelde yalnizca http/https adresleri acilir."}
    url, _typed = resolve_url(target)
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return {"error": f"Gecersiz adres: {target}"}
    return {
        "status": "site JARVIS panelinde acildi",
        "url": url,
        "panel": {"kind": "web", "url": url, "title": u.hostname.removeprefix("www."), "subtitle": "WEB"},
    }


# ------------------------------------------------------------------ haberler
_NEWS_FEED = "https://news.google.com/rss"
_NEWS_LOCALE = {"hl": "tr", "gl": "TR", "ceid": "TR:tr"}
_NEWS_MAX = 12
_NEWS_SPOKEN = 8      # modele (sesli anlatim icin) donen baslik sayisi


def _parse_news(xml_text: str) -> list[dict[str, str]]:
    """RSS -> [{title, source, published (ISO), url}]. Bozuk/eksik kayitlar atlanir."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    items: list[dict[str, str]] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        source = (node.findtext("source") or "").strip()
        if not title or urlparse(url).scheme not in ("http", "https"):
            continue
        if source and title.endswith(f" - {source}"):     # "Baslik - Kaynak" -> "Baslik"
            title = title[: -len(source) - 3].rstrip()
        published = ""
        try:
            published = parsedate_to_datetime(node.findtext("pubDate") or "").astimezone().isoformat()
        except (TypeError, ValueError):
            pass
        items.append({"title": title, "source": source, "published": published, "url": url})
        if len(items) >= _NEWS_MAX:
            break
    return items


def show_news(topic: str = "") -> dict[str, Any]:
    """Guncel haber basliklarini (bos: Turkiye gundemi; dolu: konu aramasi) JARVIS panelinde gosterir."""
    topic = (topic or "").strip()
    url = f"{_NEWS_FEED}/search" if topic else _NEWS_FEED
    params = {**_NEWS_LOCALE, **({"q": topic} if topic else {})}
    try:
        r = httpx.get(url, params=params, headers=_UA, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"error": f"Haber kaynagina ulasilamadi ({type(exc).__name__}). Haber uydurma."}
    items = _parse_news(r.text) if r.status_code == 200 else []
    if not items:
        return {"error": f"'{topic or 'gundem'}' icin haber bulunamadi. Uydurma; bulamadigini soyle."}
    title = f"Haberler · {topic}" if topic else "Gündem"
    page = "https://news.google.com/" + (f"search?q={quote(topic)}&" if topic else "?") + "hl=tr&gl=TR&ceid=TR:tr"
    return {
        "status": "haberler JARVIS panelinde acildi",
        "topic": topic or "gundem",
        "headlines": [{"title": i["title"], "source": i["source"], "published": i["published"][:16]}
                      for i in items[:_NEWS_SPOKEN]],
        "note": "YALNIZCA bu basliklari ozetle; basliklarda olmayan ayrinti uydurma. Ayrinti istenirse web_search kullan.",
        "panel": {"kind": "news", "title": title, "subtitle": f"Google Haberler · {len(items)} başlık",
                  "items": items, "url": page},
    }


# ------------------------------------------------------------------ piyasa
_YF_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"}
_YF_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
_YF_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
# Sik sorulanlar: katlanmis ad -> (Yahoo sembolu, gorunen ad)
_MARKET_ALIASES: dict[str, tuple[str, str]] = {
    "borsa": ("XU100.IS", "BIST 100"), "borsa istanbul": ("XU100.IS", "BIST 100"),
    "bist": ("XU100.IS", "BIST 100"), "bist 100": ("XU100.IS", "BIST 100"), "bist100": ("XU100.IS", "BIST 100"),
    "bist 30": ("XU030.IS", "BIST 30"), "bist30": ("XU030.IS", "BIST 30"),
    "dolar": ("USDTRY=X", "Dolar / TL"), "usd": ("USDTRY=X", "Dolar / TL"),
    "euro": ("EURTRY=X", "Euro / TL"), "eur": ("EURTRY=X", "Euro / TL"),
    "sterlin": ("GBPTRY=X", "Sterlin / TL"),
    "altin": ("GC=F", "Altın (ons, USD)"), "ons altin": ("GC=F", "Altın (ons, USD)"),
    "gumus": ("SI=F", "Gümüş (ons, USD)"), "petrol": ("BZ=F", "Brent Petrol"),
    "bitcoin": ("BTC-USD", "Bitcoin"), "btc": ("BTC-USD", "Bitcoin"),
    "ethereum": ("ETH-USD", "Ethereum"), "eth": ("ETH-USD", "Ethereum"),
    "nasdaq": ("^IXIC", "Nasdaq"), "s p 500": ("^GSPC", "S&P 500"), "sp500": ("^GSPC", "S&P 500"),
    "dow jones": ("^DJI", "Dow Jones"),
}
# donem -> (Yahoo range, interval, gorunen etiket)
MARKET_PERIODS: dict[str, tuple[str, str, str]] = {
    "1g": ("1d", "5m", "1 GÜN"), "1h": ("5d", "30m", "1 HAFTA"), "1ay": ("1mo", "1d", "1 AY"),
    "3ay": ("3mo", "1d", "3 AY"), "1y": ("1y", "1d", "1 YIL"), "5y": ("5y", "1wk", "5 YIL"),
}
_PERIOD_ALIASES = {"gun": "1g", "gunluk": "1g", "bugun": "1g", "hafta": "1h", "haftalik": "1h", "ay": "1ay",
                   "aylik": "1ay", "1 ay": "1ay", "3 ay": "3ay", "yil": "1y", "yillik": "1y", "1 yil": "1y",
                   "5 yil": "5y", "1d": "1g", "5d": "1h", "1w": "1h", "1mo": "1ay", "3mo": "3ay"}
_SUFFIX_MAX = 3   # tablodaki ada eklenebilecek en uzun cekim eki (harf)
_MARKET_NOISE = {"hisse", "hissesi", "hisseleri", "senedi", "fiyati", "fiyat", "kuru", "kur", "grafigi",
                 "grafik", "endeksi", "endeks", "ne", "kadar", "durumu", "durum", "goster"}


def _market_symbol(query: str) -> tuple[str, str] | None:
    """Kullanicinin soyledigi addan dogrulanmis (sembol, ad). Tabloda yoksa Yahoo aramasi (IST oncelikli)."""
    words = [w for w in _fold(query).split() if w not in _MARKET_NOISE]
    key = " ".join(words)
    if not key:
        return None
    if key in _MARKET_ALIASES:
        return _MARKET_ALIASES[key]
    if len(words) == 1:      # cekim eki: "borsayi", "dolari", "altinin" -> tablodaki kok
        stem = max((a for a in _MARKET_ALIASES if len(a) >= 4 and key.startswith(a)
                    and len(key) - len(a) <= _SUFFIX_MAX), key=len, default=None)
        if stem:
            return _MARKET_ALIASES[stem]
    r = httpx.get(_YF_SEARCH, params={"q": key, "quotesCount": 6, "newsCount": 0}, headers=_YF_UA, timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    quotes = [q for q in (r.json().get("quotes") or []) if q.get("symbol")]
    if not quotes:
        return None
    best = next((q for q in quotes if str(q["symbol"]).endswith(".IS")), quotes[0])
    return str(best["symbol"]), str(best.get("shortname") or best.get("longname") or best["symbol"])


def _market_series(symbol: str, period: str) -> dict[str, Any] | None:
    rng, interval, _label = MARKET_PERIODS[period]
    r = httpx.get(_YF_CHART + quote(symbol, safe="=^-."), params={"range": rng, "interval": interval},
                  headers=_YF_UA, timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    result = ((r.json().get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    points = [[int(t), float(c)] for t, c in zip(result.get("timestamp") or [], closes) if c is not None]
    if len(points) < 2:
        return None
    return {"meta": result.get("meta") or {}, "points": points}


def show_market(query: str, period: str = "1ay") -> dict[str, Any]:
    """Bir endeks, hisse, doviz ya da kripto varligin fiyat grafigini JARVIS panelinde gosterir."""
    query = (query or "").strip()
    if not query:
        return {"error": "'query' zorunlu: orn. 'borsa', 'dolar', 'bitcoin', 'Turk Hava Yollari'."}
    folded = _fold(period or "")
    period = folded if folded in MARKET_PERIODS else _PERIOD_ALIASES.get(folded, "1ay")
    try:
        found = _market_symbol(query)
        if found is None:
            return {"error": f"'{query}' icin piyasa verisi bulunamadi. Fiyat uydurma; bulamadigini soyle."}
        symbol, name = found
        data = _market_series(symbol, period)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"error": f"Piyasa verisine ulasilamadi ({type(exc).__name__}). Fiyat uydurma."}
    if data is None:
        return {"error": f"'{name}' icin grafik verisi alinamadi. Fiyat uydurma."}
    meta, points = data["meta"], data["points"]
    values = [v for _t, v in points]
    last = float(meta.get("regularMarketPrice") or values[-1])
    # Gun ici donemde degisim onceki kapanisa, digerlerinde donemin ilk degerine gore
    base = float(meta.get("chartPreviousClose") or values[0]) if period == "1g" else values[0]
    change = last - base
    stats = {
        "price": round(last, 4), "currency": str(meta.get("currency") or ""),
        "change": round(change, 4), "change_pct": round(change / base * 100, 2) if base else 0.0,
        "high": round(max(values), 4), "low": round(min(values), 4),
        "as_of": int(meta.get("regularMarketTime") or points[-1][0]),
    }
    label = MARKET_PERIODS[period][2]
    return {
        "status": "grafik JARVIS panelinde acildi",
        "name": name, "symbol": symbol, "period": label, **stats,
        "note": "Yalnizca bu rakamlari anlat (fiyat, donem degisimi, en yuksek/dusuk). Yatirim tavsiyesi verme.",
        "panel": {"kind": "chart", "title": name, "subtitle": f"{symbol} · {label}", "points": points,
                  "stats": stats, "url": f"https://finance.yahoo.com/quote/{quote(symbol, safe='=^-.')}"},
    }


# ------------------------------------------------------------------ 3B izmir haritasi
_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_PHOTON = "https://photon.komoot.io/api/"
_ROUTER = "https://routing.openstreetmap.de/{profile}/route/v1/driving/{coords}"
IZMIR_CENTER = (38.4237, 27.1428)        # Konak / Kordon
IZMIR_ZOOM = 12.0                         # tum korfez gorunur
# Arama kutulari (sol, ust, sag, alt): once merkez ilceler ("Saat Kulesi" -> Konak, Selcuk degil),
# bulunamazsa tum il. Kutu dikdortgen oldugundan komsu ile tasar; adresinde Izmir gecmeyen elenir.
_IZMIR_CORE_VIEWBOX = "26.85,38.62,27.35,38.30"
_IZMIR_VIEWBOX = "26.20,39.40,28.50,37.80"
_MAP_NOISE = {"izmir", "harita", "haritasi", "haritada", "goster", "ac", "3b", "3d"}
# Yerin turune gore kamera yakinlasmasi (MapLibre zoom). Tablo disi turler: bina / tesis.
_ZOOM_BY_KIND = {
    "state": 10.5, "province": 10.5, "county": 12.0, "city": 12.5, "town": 13.0, "municipality": 13.0,
    "district": 14.0, "suburb": 14.5, "quarter": 14.5, "village": 14.5,
    "neighbourhood": 15.5, "residential": 15.5,
    "road": 16.5, "street": 16.5, "square": 17.0,
}
_ZOOM_DEFAULT = 17.0      # bina, okul, kafe, durak...
ROUTE_MODES: dict[str, tuple[str, str, str]] = {   # ad -> (yonlendirme profili, OSM motoru, etiket)
    "araba": ("routed-car", "fossgis_osrm_car", "ARAÇ"),
    "yuruyus": ("routed-foot", "fossgis_osrm_foot", "YÜRÜYÜŞ"),
    "bisiklet": ("routed-bike", "fossgis_osrm_bike", "BİSİKLET"),
}
_MODE_ALIASES = {"arac": "araba", "otomobil": "araba", "car": "araba", "driving": "araba", "yaya": "yuruyus",
                 "yurume": "yuruyus", "yuruyerek": "yuruyus", "walk": "yuruyus", "walking": "yuruyus",
                 "bike": "bisiklet", "bisikletle": "bisiklet"}
_ROUTE_MAX_POINTS = 600
MAP_ACTIONS = {"zoom_in": "yakinlasti", "zoom_out": "uzaklasti", "rotate": "dondu", "reset": "Izmir geneline dondu"}
_MAP_ACTION_ALIASES = {"yakinlastir": "zoom_in", "yaklas": "zoom_in", "buyut": "zoom_in", "uzaklastir": "zoom_out",
                       "uzaklas": "zoom_out", "kucult": "zoom_out", "dondur": "rotate", "cevir": "rotate",
                       "sifirla": "reset", "genel": "reset"}


def _map_zoom(kind: str) -> float:
    """Yer turunden ('suburb', 'road', 'university'...) kameranin yakinlasmasi."""
    return _ZOOM_BY_KIND.get(kind, _ZOOM_DEFAULT)


def _place(lat: Any, lon: Any, name: str, address: str, kind: str) -> dict[str, Any] | None:
    try:
        return {"lat": float(lat), "lon": float(lon), "name": name, "address": address, "kind": kind}
    except (TypeError, ValueError):
        return None


# Yerlesim yeri turleri: "Cesme" denince ilce kastedilir, Bayrakli'daki ayni adli otobus duragi degil
_SETTLEMENTS = {"state", "province", "county", "city", "town", "municipality", "district", "city_district",
                "borough", "suburb", "quarter", "village", "hamlet", "neighbourhood"}


def _nominatim(place: str, viewbox: str) -> dict[str, Any] | None:
    """Kutu icindeki en iyi Izmir kaydi (koordinati sayi, adresinde 'Izmir' gecen); yerlesim yeri
    kaydi varsa o, yoksa ilk kayit."""
    r = httpx.get(_NOMINATIM, params={"q": place, "format": "jsonv2", "limit": 5, "countrycodes": "tr",
                                      "viewbox": viewbox, "bounded": 1, "accept-language": "tr"},
                  headers=_UA, timeout=_TIMEOUT)
    hits = r.json() if r.status_code == 200 else []
    found: list[dict[str, Any]] = []
    for h in hits if isinstance(hits, list) else []:
        if not isinstance(h, dict) or "izmir" not in _fold(str(h.get("display_name", ""))):
            continue
        p = _place(h.get("lat"), h.get("lon"), str(h.get("name") or place), str(h.get("display_name") or ""),
                   str(h.get("addresstype") or h.get("type") or ""))
        if p:
            found.append(p)
    return next((p for p in found if p["kind"] in _SETTLEMENTS), found[0] if found else None)


def _photon(place: str) -> dict[str, Any] | None:
    """Bulanik arama yedegi: Nominatim tum kelimeleri sirasiyla ister ("Dokuz Eylul Egitim Fakultesi
    Buca" bos doner, OSM'deki ad "... Buca Egitim Fakultesi Yerleskesi"); Photon sirayi onemsemez."""
    left, top, right, bottom = _IZMIR_VIEWBOX.split(",")
    r = httpx.get(_PHOTON, params={"q": place, "limit": 5, "bbox": f"{left},{bottom},{right},{top}",
                                   "lat": IZMIR_CENTER[0], "lon": IZMIR_CENTER[1]},
                  headers=_UA, timeout=_TIMEOUT)
    data = r.json() if r.status_code == 200 else {}
    feats = (data.get("features") or []) if isinstance(data, dict) else []
    for f in feats:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if "izmir" not in _fold(str(props.get("state", ""))) or len(coords) < 2:
            continue
        parts = [props.get(k) for k in ("name", "street", "district", "city", "county", "state")]
        address = ", ".join(dict.fromkeys(str(x) for x in parts if x))
        kind = str(props.get("type") or props.get("osm_value") or "")
        found = _place(coords[1], coords[0], str(props.get("name") or place), address, kind)
        if found:
            return found
    return None


def _geocode(place: str) -> dict[str, Any] | None:
    """Izmir ilinde bir yer. Sira: merkezdeki yerlesim yeri > ildeki yerlesim yeri > merkezdeki kayit
    ("Saat Kulesi" -> Konak) > ildeki kayit > Photon (bulanik). Hicbirine ulasilamazsa HTTPError."""
    failed: httpx.HTTPError | None = None

    def attempt(search: Callable[[], dict[str, Any] | None]) -> dict[str, Any] | None:
        nonlocal failed
        try:
            return search()
        except httpx.HTTPError as exc:
            failed = exc
        except ValueError:
            pass
        return None

    core = attempt(lambda: _nominatim(place, _IZMIR_CORE_VIEWBOX))
    if core and core["kind"] in _SETTLEMENTS:
        return core
    wide = attempt(lambda: _nominatim(place, _IZMIR_VIEWBOX))
    if wide and wide["kind"] in _SETTLEMENTS:
        return wide
    hit = core or wide or attempt(lambda: _photon(place))
    if hit is None and failed is not None:
        raise failed
    return hit


_HERE = {"konumum", "konum", "buradan", "burasi", "burada", "bulundugum yer", "bulundugum yerden",
         "benim konumum", "su anki konumum", "here", "my location"}


class _NoPhoneFix(Exception):
    """'konumum' istendi ama telefon konumu alinamadi."""


def _locate(place: str) -> dict[str, Any] | None:
    """`_geocode` + 'konumum': telefon uygulamasinin GPS'i (tools/phone_tools.py)."""
    if _fold(place) not in _HERE:
        return _geocode(place)
    from tools.phone_tools import current_location

    fix = current_location()
    if fix is None:
        raise _NoPhoneFix
    return _place(fix[0], fix[1], "Konumunuz", "telefon GPS", "here")


def _wants_city(place: str) -> bool:
    return not [w for w in _fold(place).split() if w not in _MAP_NOISE]


def show_map(place: str = "") -> dict[str, Any]:
    """Izmir'de bir yeri (bos: tum sehir) 3B haritada gosterir. Koordinati arac bulur (Nominatim /
    Photon, Izmir il siniri icinde); model koordinat UYDURAMAZ."""
    place = " ".join((place or "").split())
    if _wants_city(place):
        lat, lon = IZMIR_CENTER
        zoom, label, address = IZMIR_ZOOM, "İzmir", ""
    else:
        try:
            hit = _geocode(place)
        except httpx.HTTPError as exc:
            return {"error": f"Harita aramasina ulasilamadi ({type(exc).__name__}). Konum uydurma."}
        if not hit:
            return {"error": f"Izmir'de '{place}' bulunamadi. Konum uydurma; bulamadigini soyle."}
        lat, lon, label, address = hit["lat"], hit["lon"], hit["name"], hit["address"]
        zoom = _map_zoom(hit["kind"])
    osm = f"https://www.openstreetmap.org/#map={int(round(zoom))}/{lat:.5f}/{lon:.5f}"
    return {
        "status": "3B harita JARVIS panelinde acildi",
        "place": label,
        "address": address,
        "lat": round(lat, 6), "lon": round(lon, 6),
        "note": "Yer hakkinda 'address' disinda bilgi uydurma.",
        "panel": {"kind": "map", "lat": lat, "lon": lon, "zoom": zoom, "label": label, "title": label,
                  "subtitle": "İZMİR · 3B HARİTA", "url": osm},
    }


def _thin(coords: list[list[float]], limit: int = _ROUTE_MAX_POINTS) -> list[list[float]]:
    """Cizgiyi panele tasinabilir boyuta indirir; ilk ve son nokta korunur."""
    if len(coords) <= limit:
        return coords
    step = (len(coords) - 1) / (limit - 1)
    return [coords[round(i * step)] for i in range(limit)]


def _route_text(meters: float, seconds: float) -> tuple[str, str]:
    km = f"{meters / 1000:.1f}".replace(".", ",") + " km" if meters >= 1000 else f"{round(meters)} m"
    minutes = max(1, round(seconds / 60))
    dur = f"{minutes // 60} sa {minutes % 60} dk" if minutes >= 60 else f"{minutes} dk"
    return km, dur


def show_route(origin: str, destination: str, mode: str = "araba") -> dict[str, Any]:
    """Izmir'de iki yer arasindaki rotayi 3B haritada cizer; mesafe ve sureyi doner (araba / yuruyus /
    bisiklet). Toplu tasima icin plan_route. Yerleri ve yolu arac bulur; model UYDURAMAZ."""
    origin, destination = " ".join((origin or "").split()), " ".join((destination or "").split())
    if not origin or not destination:
        return {"error": "'origin' ve 'destination' zorunlu. Baslangic noktasi soylenmediyse kullaniciya sor."}
    folded = _fold(mode or "")
    mode = folded if folded in ROUTE_MODES else _MODE_ALIASES.get(folded, "araba")
    profile, engine, mode_label = ROUTE_MODES[mode]
    try:
        a, b = _locate(origin), _locate(destination)
    except httpx.HTTPError as exc:
        return {"error": f"Harita aramasina ulasilamadi ({type(exc).__name__}). Rota uydurma."}
    except _NoPhoneFix:
        return {"error": "Telefon konumu alinamadi (uygulama bagli degil ya da GPS kapali). Baslangic yerini sor."}
    if a is None or b is None:
        missing = ", ".join(n for n, h in ((origin, a), (destination, b)) if h is None)
        return {"error": f"Izmir'de bulunamadi: {missing}. Rota uydurma; bulamadigini soyle."}
    try:
        r = httpx.get(_ROUTER.format(profile=profile, coords=f"{a['lon']},{a['lat']};{b['lon']},{b['lat']}"),
                      params={"overview": "full", "geometries": "geojson"}, headers=_UA, timeout=15.0)
        route = (r.json().get("routes") or [None])[0] if r.status_code == 200 else None
        coords = [[float(x), float(y)] for x, y in (route or {}).get("geometry", {}).get("coordinates", [])]
        meters, seconds = float(route["distance"]), float(route["duration"])   # type: ignore[index]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"error": f"Rota hesaplanamadi ({type(exc).__name__}). Rota uydurma."}
    if len(coords) < 2:
        return {"error": f"'{a['name']}' ile '{b['name']}' arasinda {mode} rotasi bulunamadi."}
    km, dur = _route_text(meters, seconds)
    title = f"{a['name']} → {b['name']}"
    osm = (f"https://www.openstreetmap.org/directions?engine={engine}"
           f"&route={a['lat']:.5f},{a['lon']:.5f};{b['lat']:.5f},{b['lon']:.5f}")
    return {
        "status": "rota 3B haritada cizildi",
        "origin": a["name"], "destination": b["name"], "mode": mode,
        "origin_address": a["address"], "destination_address": b["address"],
        "distance": km, "duration": dur,
        "note": ("Mesafe ve sureyi soyle; sure trafiksiz tahmindir. Mesafe beklenenden cok farkliysa sebep "
                 "trafik DEGIL, yanlis yer eslesmesidir: adreslere bak, kullaniciya hangi yerin bulundugunu "
                 "soyle ve daha belirgin adla (ilce/mahalle ekleyerek) yeniden dene. Toplu tasima icin plan_route."),
        "panel": {"kind": "map", "title": title, "subtitle": f"ROTA · {km} · {dur} · {mode_label}",
                  "lat": b["lat"], "lon": b["lon"], "zoom": 15.0, "label": b["name"], "url": osm,
                  "route": {"coords": _thin(coords), "distance": km, "duration": dur, "mode": mode_label,
                            "origin": {"lat": a["lat"], "lon": a["lon"], "label": a["name"]},
                            "destination": {"lat": b["lat"], "lon": b["lon"], "label": b["name"]}}},
    }


def map_control(action: str) -> dict[str, Any]:
    """Acik 3B haritayi yakinlastirir, uzaklastirir, dondurur ya da Izmir geneline dondurur."""
    folded = _fold(action or "")
    # "zoom_in" ya da Turkce komut; "haritayi biraz yakinlastir" gibi cumlede herhangi bir kelime
    action = folded.replace(" ", "_") if folded.replace(" ", "_") in MAP_ACTIONS else next(
        (_MAP_ACTION_ALIASES[w] for w in folded.split() if w in _MAP_ACTION_ALIASES), "")
    if not action:
        return {"error": f"Bilinmeyen harita komutu. Gecerli: {', '.join(MAP_ACTIONS)}."}
    return {"status": f"harita {MAP_ACTIONS[action]}", "panel": {"kind": "map_control", "action": action}}


# ------------------------------------------------------------------ hava + bilgi karti
def show_weather(location: str = "") -> dict[str, Any]:
    """Bir sehrin guncel hava durumunu ve kisa tahminini JARVIS panelinde gosterir."""
    from tools.quick_tools import get_weather

    location = (location or "").strip()
    if not location:
        try:
            from config.settings import get_settings

            location = get_settings().hud_weather_location
        except Exception:  # noqa: BLE001 - ayarlar yuklenemezse konum sorulur
            location = ""
    if not location:
        return {"error": "Hangi sehir? Konum belirtilmedi."}
    data = get_weather(location)
    if "error" in data:
        return data
    place = str(data.get("konum", location))
    return {
        "status": "hava durumu JARVIS panelinde acildi",
        **data,
        "panel": {"kind": "weather", "title": place, "subtitle": "HAVA DURUMU",
                  "now": data.get("simdi") or {}, "days": data.get("tahmin") or []},
    }


INFO_TITLE_MAX = 120
INFO_BODY_MAX = 6000


def show_info(title: str, body: str) -> dict[str, Any]:
    """JARVIS'in kendi hazirladigi yazili icerigi (ozet, tarif, adim listesi, karsilastirma tablosu)
    panelde gosterir. Bu modulde icerigi MODELIN urettigi tek arac budur: govde sade Markdown'dir,
    panel baglanti ve uzak gorsel yuklemez."""
    title = " ".join((title or "").split())[:INFO_TITLE_MAX]
    body = (body or "").strip()
    if not title or not body:
        return {"error": "'title' ve 'body' zorunlu."}
    truncated = len(body) > INFO_BODY_MAX
    return {
        "status": "bilgi karti JARVIS panelinde acildi" + (" (govde kisaltildi)" if truncated else ""),
        "title": title,
        "panel": {"kind": "info", "title": title, "subtitle": "BİLGİ KARTI", "body": body[:INFO_BODY_MAX]},
    }


# ------------------------------------------------------------------ spotify + kapat
def show_spotify() -> dict[str, Any]:
    """Spotify 'su an caliyor' kartini JARVIS panelinde gosterir (kapak, sarki, onceki/duraklat/sonraki)."""
    if not spotify_enabled():
        return {"error": "Spotify yapilandirilmamis (.env SPOTIFY_CLIENT_ID/SECRET + `python scripts/spotify_auth.py`)."}
    state = spotify_playback_state()
    if "error" in state:
        return state
    out = {k: v for k, v in state.items() if k not in ("image", "progress_ms", "duration_ms")}
    out["status"] = "Spotify karti JARVIS panelinde acildi"
    out["panel"] = {"kind": "spotify", "title": "Spotify", "subtitle": str(state.get("device") or "")}
    return out


def close_panel() -> dict[str, Any]:
    """JARVIS arayuzundeki icerik panelini (video, haber, grafik, belge, site, Spotify...) kapatir."""
    return {"status": "panel kapatildi", "panel": {"kind": "close"}}
