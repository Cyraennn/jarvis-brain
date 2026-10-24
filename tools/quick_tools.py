"""Hizli sesli araclar - web arama, hava, hesap, doviz, ceviri, pano.

Self-contained: kendi genai/httpx istemcisini kurar. Anahtarsiz halka acik API'ler.
"""

from __future__ import annotations

import ast
import ctypes
import math
import operator
import sys
from functools import lru_cache
from typing import Any

import httpx

from config.settings import get_settings


# --------------------------------------------------------------------- genai
@lru_cache(maxsize=1)
def _genai():  # noqa: ANN202
    from google import genai
    from google.genai import types

    s = get_settings()
    return genai.Client(
        api_key=s.gemini_api_key,
        http_options=types.HttpOptions(api_version=s.agents_api_version, timeout=45_000),
    ), types


async def _gen(prompt: str, *, grounded: bool = False) -> str:
    from agents.genai_util import generate_with_retry

    client, types = _genai()
    s = get_settings()
    cfg_kw: dict[str, Any] = {"temperature": 0.2}
    if grounded:
        try:
            cfg_kw["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        except Exception:  # noqa: BLE001
            pass
    config = types.GenerateContentConfig(**cfg_kw)
    if grounded:
        # Google arama topraklamasinin kotasi hesap genelinde: 429 verince zincirdeki her modeli uc
        # kez denemek ~1 dk suruyor ve canli oturum beklerken kopuyordu. Ayrica zincirin sonunda
        # yerel modele dusuluyor, o da web'e bakmadan cevap uyduruyordu. Tek, dogrudan deneme;
        # hata cagirana gider ve DuckDuckGo'ya gecilir.
        import asyncio

        resp = await asyncio.wait_for(
            client.aio.models.generate_content(model=s.agent_model_chain[0], contents=prompt, config=config),
            timeout=45.0,
        )
        return (getattr(resp, "text", None) or "").strip()
    resp = await generate_with_retry(
        client, model=s.agent_model_chain, contents=prompt, config=config,
    )
    return (getattr(resp, "text", None) or "").strip()


# Google arama topraklamasi kota/izin hatasi verirse bu sure boyunca denenmez
# (her aramada 4 modeli bosuna 429'a sokmamak icin); dogrudan DuckDuckGo'ya gecilir.
GROUNDING_COOLDOWN_S = 3600.0
_grounding_blocked_until = 0.0


def _grounding_available() -> bool:
    import time

    return time.monotonic() >= _grounding_blocked_until


def _block_grounding(reason: str) -> None:
    import time

    from loguru import logger

    global _grounding_blocked_until
    _grounding_blocked_until = time.monotonic() + GROUNDING_COOLDOWN_S
    logger.warning(f"Google arama topraklamasi kullanilamiyor ({reason[:80]}); "
                   f"{GROUNDING_COOLDOWN_S / 60:.0f} dk DuckDuckGo kullanilacak")


def duckduckgo_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """Anahtarsiz web + haber aramasi (DuckDuckGo, `ddgs`). Ham sonuclari doner."""
    q = (query or "").strip()
    if not q:
        return {"error": "arama sorgusu bos"}
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "DuckDuckGo icin `pip install ddgs` gerekli."}
    n = max(1, int(max_results))
    results: list[dict[str, str]] = []
    errors: list[str] = []
    ddg = DDGS()
    try:  # haberler: tarihli ve guncel
        for r in ddg.news(q, region="tr-tr", max_results=n):
            date = str(r.get("date", ""))[:10]
            results.append({"type": "haber", "date": date if date[:4].isdigit() else "",
                            "source": r.get("source", ""), "title": r.get("title", ""),
                            "snippet": r.get("body", "")[:400], "url": r.get("url", "")})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"haber: {type(exc).__name__}")
    try:
        for r in ddg.text(q, region="tr-tr", max_results=n):
            results.append({"type": "web", "title": r.get("title", ""),
                            "snippet": r.get("body", "")[:400], "url": r.get("href", "")})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"web: {type(exc).__name__}")
    if not results:
        return {"error": f"DuckDuckGo sonuc vermedi ({', '.join(errors) or 'bos'})"}
    results.sort(key=lambda r: r.get("date", ""), reverse=True)  # haberler en yeni once
    return {"query": q, "backend": "duckduckgo", "count": len(results), "results": results}


async def web_search(query: str) -> dict[str, Any]:
    """Web'de arar ve kisa ozet dondurur: Google topraklamasi, olmazsa DuckDuckGo + ozet."""
    import asyncio

    q = (query or "").strip()
    if not q:
        return {"error": "arama sorgusu bos"}
    if _grounding_available():
        try:
            text = await _gen(
                f"Su konuyu web'de arastir ve 3-5 cumlede, guncel bilgiyle Turkce ozetle: {q}",
                grounded=True,
            )
            if text:
                return {"query": q, "answer": text}
        except Exception as exc:  # noqa: BLE001
            _block_grounding(str(exc))
    found = await asyncio.to_thread(duckduckgo_search, q, 6)
    if "error" in found:
        return found
    digest = "\n".join(
        f"- {r.get('date', '')} {r['title']}: {r['snippet']}" for r in found["results"][:10]
    )
    try:
        text = await _gen(
            "Asagidaki guncel arama sonuclarina dayanarak soruyu 3-5 cumlede Turkce yanitla. "
            f"Sonuclarda olmayan bilgiyi uydurma.\nSoru: {q}\nSonuclar:\n{digest}"
        )
    except Exception:  # noqa: BLE001 - ozetlenemezse ham basliklar
        text = digest[:1200]
    return {"query": q, "answer": text, "backend": "duckduckgo",
            "sources": [r["url"] for r in found["results"][:5]]}


def web_research(query: str, max_sources: int = 8) -> dict[str, Any]:
    """GUNCEL ve detayli web arastirmasi (ajanlar icin): Google topraklamasi -> DuckDuckGo.

    Senkron ve her cagrida kendi istemcisini acar: ajan araclari ayri thread'lerde
    (to_thread) calistigi icin paylasilan async istemciye / event loop'a baglanmaz.
    DuckDuckGo yolunda ham sonuclar (baslik, tarih, ozet, link) doner; sentezi ajan yapar.
    """
    q = (query or "").strip()
    if not q:
        return {"error": "arama sorgusu bos"}
    s = get_settings()
    if s.gemini_api_key and _grounding_available():
        result = _grounded_research(q, max_sources)
        if "error" not in result:
            return result
        _block_grounding(result["error"])
    return duckduckgo_search(q, max_results=max_sources)


def _grounded_research(q: str, max_sources: int) -> dict[str, Any]:
    from datetime import datetime

    from google import genai
    from google.genai import types

    s = get_settings()
    client = genai.Client(
        api_key=s.gemini_api_key,
        http_options=types.HttpOptions(api_version=s.agents_api_version, timeout=60_000),
    )
    prompt = (
        f"Bugunun tarihi: {datetime.now():%d.%m.%Y}. Su konuyu Google'da arastir ve EN GUNCEL "
        f"bilgiyle Turkce, maddeler halinde detayli ozetle (tarihleri belirt, eski bilgiyi yeni "
        f"diye sunma): {q}"
    )
    cfg = types.GenerateContentConfig(
        temperature=0.2, tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    last = ""
    for model in s.agent_model_chain:
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
        except Exception as exc:  # noqa: BLE001 - kota/404 -> siradaki model
            last = f"{type(exc).__name__}: {str(exc)[:120]}"
            continue
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            continue
        sources: list[dict[str, str]] = []
        try:
            meta = resp.candidates[0].grounding_metadata
            for chunk in (getattr(meta, "grounding_chunks", None) or [])[: max(1, int(max_sources))]:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    sources.append({"title": getattr(web, "title", "") or "", "url": web.uri})
        except (AttributeError, IndexError, TypeError):
            pass
        return {"query": q, "backend": "google", "model": model, "answer": text, "sources": sources}
    return {"error": f"Google aramasi basarisiz: {last or 'bos yanit'}"}


async def translate(text: str, target_lang: str = "en") -> dict[str, Any]:
    """Metni hedef dile cevirir (target_lang: en, tr, de, fr, ...)."""
    if not (text or "").strip():
        return {"error": "metin bos"}
    try:
        out = await _gen(
            f"Asagidaki metni '{target_lang}' diline dogal ve akici cevir. "
            f"SADECE ceviriyi yaz:\n\n{text}"
        )
        return {"target": target_lang, "translation": out}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Ceviri basarisiz: {exc}"}


# --------------------------------------------------------------------- hava
def get_weather(location: str) -> dict[str, Any]:
    """Bir sehrin guncel hava durumunu ve kisa tahminini verir (open-meteo, anahtarsiz)."""
    loc = (location or "").strip()
    if not loc:
        return {"error": "konum bos"}
    try:
        with httpx.Client(timeout=12.0) as c:
            g = c.get("https://geocoding-api.open-meteo.com/v1/search",
                      params={"name": loc, "count": 1, "language": "tr"}).json()
            if not g.get("results"):
                return {"error": f"Konum bulunamadi: {loc}"}
            p = g["results"][0]
            lat, lon = p["latitude"], p["longitude"]
            w = c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon, "current": "temperature_2m,relative_humidity_2m,"
                "apparent_temperature,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "auto", "forecast_days": 3,
            }).json()
        cur = w.get("current", {})
        daily = w.get("daily", {})
        codes = {0: "acik", 1: "az bulutlu", 2: "parcali bulutlu", 3: "kapali",
                 45: "sisli", 48: "kirragi sis", 51: "cisenti", 61: "yagmurlu",
                 63: "yagmurlu", 65: "kuvvetli yagmur", 71: "karli", 73: "karli",
                 75: "yogun kar", 80: "saganak", 95: "gok gurultulu", 96: "dolulu firtina"}
        return {
            "konum": p["name"] + (f", {p.get('country', '')}" if p.get("country") else ""),
            "simdi": {
                "sicaklik": cur.get("temperature_2m"),
                "hissedilen": cur.get("apparent_temperature"),
                "nem": cur.get("relative_humidity_2m"),
                "ruzgar_kmh": cur.get("wind_speed_10m"),
                "durum": codes.get(cur.get("weather_code"), "?"),
            },
            "tahmin": [
                {"gun": daily["time"][i], "min": daily["temperature_2m_min"][i],
                 "max": daily["temperature_2m_max"][i],
                 "durum": codes.get(daily["weather_code"][i], "?")}
                for i in range(min(3, len(daily.get("time", []))))
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Hava durumu alinamadi: {exc}"}


# --------------------------------------------------------------------- hesap
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
         "log": math.log, "log10": math.log10, "exp": math.exp, "abs": abs,
         "round": round, "floor": math.floor, "ceil": math.ceil, "pi": math.pi, "e": math.e}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("gecersiz sabit")
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Name) and node.id in _FUNCS and not callable(_FUNCS[node.id]):
        return _FUNCS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval_node(a) for a in node.args])
    raise ValueError("desteklenmeyen ifade")


def calculate(expression: str) -> dict[str, Any]:
    """Matematik ifadesi hesaplar (guvenli). Orn: '(2+3)*4', 'sqrt(144)', 'sin(pi/2)'."""
    expr = (expression or "").strip().replace("^", "**").replace(",", ".")
    if not expr:
        return {"error": "ifade bos"}
    try:
        tree = ast.parse(expr, mode="eval")
        val = _eval_node(tree.body)
        return {"expression": expr, "result": round(val, 10) if isinstance(val, float) else val}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Hesaplanamadi: {exc}"}


# --------------------------------------------------------------------- doviz
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict[str, Any]:
    """Doviz cevirir (frankfurter.app, anahtarsiz). Orn: 100 USD -> TRY."""
    f = (from_currency or "").strip().upper()
    t = (to_currency or "").strip().upper()
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return {"error": "miktar sayi degil"}
    if not f or not t:
        return {"error": "para birimleri gerekli"}
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as c:
            r = c.get("https://api.frankfurter.dev/v1/latest",
                      params={"amount": amt, "from": f, "to": t}).json()
            if "rates" not in r or t not in r["rates"]:
                # yedek: open.er-api.com
                r2 = c.get(f"https://open.er-api.com/v6/latest/{f}").json()
                rate = (r2.get("rates") or {}).get(t)
                if rate is None:
                    return {"error": f"Cevrilemedi: {f}->{t}"}
                return {"from": f"{amt} {f}", "to": f"{round(amt * rate, 2)} {t}",
                        "rate": round(rate, 4), "date": r2.get("time_last_update_utc", "")[:16]}
        return {"from": f"{amt} {f}", "to": f"{round(r['rates'][t], 2)} {t}",
                "rate": round(r["rates"][t] / amt, 4), "date": r.get("date")}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Doviz alinamadi: {exc}"}


# --------------------------------------------------------------------- pano
def clipboard_get() -> dict[str, Any]:
    """Panodaki metni okur."""
    if sys.platform != "win32":
        return {"error": "yalnizca Windows"}
    try:
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        u.OpenClipboard(0)
        try:
            h = u.GetClipboardData(13)  # CF_UNICODETEXT
            if not h:
                return {"text": ""}
            k.GlobalLock.restype = ctypes.c_void_p
            ptr = k.GlobalLock(h)
            text = ctypes.wstring_at(ptr) if ptr else ""
            k.GlobalUnlock(h)
            return {"text": text}
        finally:
            u.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Pano okunamadi: {exc}"}


def clipboard_set(text: str) -> dict[str, Any]:
    """Panoya metin koyar."""
    if sys.platform != "win32":
        return {"error": "yalnizca Windows"}
    try:
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        data = (text or "").encode("utf-16-le") + b"\x00\x00"
        GMEM_MOVEABLE = 0x0002
        k.GlobalAlloc.restype = ctypes.c_void_p
        k.GlobalLock.restype = ctypes.c_void_p
        h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = k.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        k.GlobalUnlock(h)
        u.OpenClipboard(0)
        u.EmptyClipboard()
        u.SetClipboardData(13, h)
        u.CloseClipboard()
        return {"status": "panoya kopyalandi", "length": len(text or "")}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Panoya yazilamadi: {exc}"}
