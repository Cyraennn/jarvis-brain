"""Panel icerik araclari (haber, piyasa, hava, bilgi karti) - agsiz testler. Veriyi arac bulur;
model baslik, sembol ya da fiyat uyduramaz: bulunamayan icin panel acilmaz."""
from __future__ import annotations

import httpx
import pytest

from tools import panel_tools, quick_tools, tool_runner
from tools.tool_declarations import build_declarations
from tools.tool_runner import ToolRunner

CONTENT_TOOLS = {"show_news", "show_market", "show_weather", "show_map", "show_route", "map_control", "show_info"}
RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Haberler</title>
<item><title>Merkez Bankası faiz kararını açıkladı - Anadolu Ajansı</title>
  <link>https://news.google.com/rss/articles/abc?oc=5</link>
  <pubDate>Mon, 12 Oct 2026 12:38:00 GMT</pubDate><source url="https://www.aa.com.tr">Anadolu Ajansı</source></item>
<item><title>Başlıksız bağlantı</title><link>javascript:alert(1)</link></item>
<item><title></title><link>https://example.com/bos</link></item>
<item><title>Tarihsiz haber - Sözcü</title><link>https://example.com/b</link>
  <pubDate>bozuk</pubDate><source>Sözcü</source></item>
</channel></rss>"""


class Resp:
    def __init__(self, status: int, data=None, text: str = "") -> None:
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        if self._data is None:
            raise ValueError("json yok")
        return self._data


def _chart(closes, *, price=None, prev=None, currency="TRY"):
    meta = {"currency": currency, "regularMarketPrice": price if price is not None else closes[-1],
            "regularMarketTime": 1_791_800_000}
    if prev is not None:
        meta["chartPreviousClose"] = prev
    return {"chart": {"result": [{"meta": meta, "timestamp": [1_791_000_000 + i * 86_400 for i in range(len(closes))],
                                  "indicators": {"quote": [{"close": closes}]}}]}}


@pytest.fixture()
def yahoo(monkeypatch):
    """Yahoo: yalnizca THYAO.IS / XU100.IS / USDTRY=X var; arama 'turk hava yollari'ni bulur."""
    calls: list[tuple[str, dict]] = []
    charts = {"XU100.IS": _chart([100.0, 110.0, None, 90.0, 120.0]),
              "THYAO.IS": _chart([300.0, 285.75]),
              "USDTRY=X": _chart([49.20, 49.30, 49.32], price=49.32, prev=49.00)}

    def fake(url, params=None, **_kw):
        calls.append((url, dict(params or {})))
        if url.startswith(panel_tools._YF_SEARCH):
            if "turk hava" in params["q"]:
                return Resp(200, {"quotes": [{"symbol": "TKHVY", "shortname": "Turk Hava Yollari AO"},
                                             {"symbol": "THYAO.IS", "shortname": "TURK HAVA YOLLARI"}]})
            return Resp(200, {"quotes": []})
        symbol = url.removeprefix(panel_tools._YF_CHART).replace("%3D", "=")
        return Resp(200, charts[symbol]) if symbol in charts else Resp(404, {"chart": {"result": None}})

    monkeypatch.setattr(panel_tools.httpx, "get", fake)
    return calls


def test_declared_and_registered():
    assert CONTENT_TOOLS <= {d.name for d in build_declarations()}
    assert CONTENT_TOOLS <= set(ToolRunner().tool_names)


# ------------------------------------------------------------------ haberler
def test_news_parses_feed_and_skips_bad_items(monkeypatch):
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(panel_tools.httpx, "get",
                        lambda url, params=None, **kw: seen.append((url, params)) or Resp(200, text=RSS))
    r = panel_tools.show_news()
    assert seen[0][0] == "https://news.google.com/rss" and "q" not in seen[0][1]
    items = r["panel"]["items"]
    assert [i["title"] for i in items] == ["Merkez Bankası faiz kararını açıkladı", "Tarihsiz haber"]
    assert items[0]["source"] == "Anadolu Ajansı" and items[0]["published"].startswith("2026-10-12T")
    assert items[1]["published"] == ""                       # bozuk tarih haberi dusurmez
    assert r["panel"]["kind"] == "news" and r["panel"]["title"] == "Gündem"
    assert r["headlines"][0] == {"title": items[0]["title"], "source": "Anadolu Ajansı",
                                 "published": items[0]["published"][:16]}


def test_news_topic_uses_search_feed(monkeypatch):
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(panel_tools.httpx, "get",
                        lambda url, params=None, **kw: seen.append((url, params)) or Resp(200, text=RSS))
    r = panel_tools.show_news("  ekonomi ")
    assert seen[0][0].endswith("/rss/search") and seen[0][1]["q"] == "ekonomi"
    assert r["panel"]["title"] == "Haberler · ekonomi" and "q=ekonomi" in r["panel"]["url"]


@pytest.mark.parametrize("resp", [Resp(200, text="<rss><channel/></rss>"), Resp(200, text="bozuk <xml"),
                                  Resp(503, text=RSS)])
def test_news_without_items_does_not_open(monkeypatch, resp):
    monkeypatch.setattr(panel_tools.httpx, "get", lambda *a, **kw: resp)
    r = panel_tools.show_news("uzay")
    assert "error" in r and "panel" not in r


def test_news_network_error(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("yok")

    monkeypatch.setattr(panel_tools.httpx, "get", boom)
    assert "ulasilamadi" in panel_tools.show_news()["error"]


# ------------------------------------------------------------------ piyasa
def test_market_alias_needs_no_search(yahoo):
    r = panel_tools.show_market("Borsayı göster", "1ay")
    assert all(not url.startswith(panel_tools._YF_SEARCH) for url, _p in yahoo)
    assert (r["symbol"], r["name"], r["period"]) == ("XU100.IS", "BIST 100", "1 AY")
    assert len(r["panel"]["points"]) == 4                     # bos (None) kapanis atlanir
    assert (r["price"], r["high"], r["low"]) == (120.0, 120.0, 90.0)
    assert (r["change"], r["change_pct"]) == (20.0, 20.0)     # donemin ilk degerine gore
    assert r["panel"]["kind"] == "chart" and r["panel"]["stats"]["currency"] == "TRY"


@pytest.mark.parametrize(("query", "symbol"), [("doları", "USDTRY=X"), ("BIST 100 endeksi", "XU100.IS"),
                                                ("borsanın durumu", "XU100.IS")])
def test_market_alias_tolerates_turkish_suffixes(yahoo, query, symbol):
    assert panel_tools.show_market(query)["symbol"] == symbol
    assert all(not url.startswith(panel_tools._YF_SEARCH) for url, _p in yahoo)


def test_market_resolves_company_name_preferring_istanbul(yahoo):
    r = panel_tools.show_market("Türk Hava Yolları hissesi", "3 ay")
    assert yahoo[0][1]["q"] == "turk hava yollari"             # dolgu kelimeler ayiklanir
    assert (r["symbol"], r["period"]) == ("THYAO.IS", "3 AY")
    assert yahoo[-1][1] == {"range": "3mo", "interval": "1d"}
    assert r["change_pct"] == -4.75


def test_market_intraday_change_is_against_previous_close(yahoo):
    r = panel_tools.show_market("dolar", "bugün")
    assert yahoo[-1][1] == {"range": "1d", "interval": "5m"}
    assert (r["change"], r["change_pct"]) == (0.32, 0.65)


def test_market_unknown_period_falls_back_to_month(yahoo):
    assert panel_tools.show_market("bist", "yuz yil")["period"] == "1 AY"


@pytest.mark.parametrize("query", ["", "hisse fiyatı", "olmayan sirket"])
def test_market_unknown_asset_does_not_open(yahoo, query):
    r = panel_tools.show_market(query)
    assert "error" in r and "panel" not in r


def test_market_symbol_without_data_does_not_open(yahoo):
    r = panel_tools.show_market("bitcoin")                     # tabloda var ama veri yok
    assert "error" in r and "panel" not in r


def test_market_network_error(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ReadTimeout("zaman asimi")

    monkeypatch.setattr(panel_tools.httpx, "get", boom)
    assert "ulasilamadi" in panel_tools.show_market("borsa")["error"]


# ------------------------------------------------------------------ hava
WEATHER = {"konum": "İzmir, Türkiye", "simdi": {"sicaklik": 18.5, "durum": "saganak"},
           "tahmin": [{"gun": "2026-10-12", "min": 16.0, "max": 26.0, "durum": "saganak"}]}


def test_weather_card_reuses_weather_tool(monkeypatch):
    asked: list[str] = []
    monkeypatch.setattr(quick_tools, "get_weather", lambda loc: asked.append(loc) or dict(WEATHER))
    r = panel_tools.show_weather("İzmir")
    assert asked == ["İzmir"] and r["simdi"]["sicaklik"] == 18.5
    assert r["panel"] == {"kind": "weather", "title": "İzmir, Türkiye", "subtitle": "HAVA DURUMU",
                          "now": WEATHER["simdi"], "days": WEATHER["tahmin"]}


def test_weather_error_passes_through(monkeypatch):
    monkeypatch.setattr(quick_tools, "get_weather", lambda loc: {"error": f"Konum bulunamadi: {loc}"})
    r = panel_tools.show_weather("Atlantis")
    assert r == {"error": "Konum bulunamadi: Atlantis"}


# ------------------------------------------------------------------ 3b harita
ALSANCAK = [{"lat": "38.4378", "lon": "27.1428", "name": "Alsancak", "addresstype": "suburb",
             "display_name": "Alsancak, Konak, İzmir, Türkiye"}]


def test_map_without_place_shows_whole_city(monkeypatch):
    monkeypatch.setattr(panel_tools.httpx, "get", lambda *a, **k: pytest.fail("arama gerekmez"))
    for place in ("", "izmir haritasi", "  İzmir  "):
        p = panel_tools.show_map(place)["panel"]
        assert p["kind"] == "map" and (p["lat"], p["lon"]) == panel_tools.IZMIR_CENTER
        assert p["zoom"] == panel_tools.IZMIR_ZOOM and p["label"] == "İzmir"


def test_map_finds_place_inside_izmir(monkeypatch):
    boxes: list[str] = []

    def fake_get(url, params=None, **kw):
        boxes.append(params["viewbox"])
        assert params["bounded"] == 1
        # merkezde yok; il kutusunda once komsu ildeki ayni adli yer, sonra Izmir'deki
        if params["viewbox"] == panel_tools._IZMIR_CORE_VIEWBOX:
            return Resp(200, [])
        return Resp(200, [{"lat": "38.45", "lon": "28.27", "name": "Alsancak", "display_name": "Alsancak, Salihli, Manisa"},
                          *ALSANCAK])

    monkeypatch.setattr(panel_tools.httpx, "get", fake_get)
    r = panel_tools.show_map("Alsancak")
    assert boxes == [panel_tools._IZMIR_CORE_VIEWBOX, panel_tools._IZMIR_VIEWBOX]   # once merkez, sonra il
    assert r["lat"] == 38.4378 and r["address"].startswith("Alsancak")
    p = r["panel"]
    assert p["kind"] == "map" and p["label"] == "Alsancak" and p["subtitle"] == "İZMİR · 3B HARİTA"
    assert p["url"].startswith("https://www.openstreetmap.org/#map=")


@pytest.mark.parametrize("resp", [Resp(200, []), Resp(200, [{"name": "x"}]), Resp(500, None), Resp(200, None)])
def test_map_unknown_place_opens_nothing(monkeypatch, resp):
    monkeypatch.setattr(panel_tools.httpx, "get", lambda *a, **k: resp)
    r = panel_tools.show_map("Atlantis")
    assert "error" in r and "panel" not in r


def test_map_network_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("yok")

    monkeypatch.setattr(panel_tools.httpx, "get", boom)
    assert "ulasilamadi" in panel_tools.show_map("Bornova")["error"]


FACULTY = {"features": [
    {"properties": {"name": "Kordon", "state": "Manisa"}, "geometry": {"coordinates": [28.27, 38.45]}},
    {"properties": {"name": "Dokuz Eylül Üniversitesi Buca Eğitim Fakültesi Yerleşkesi", "district": "Vali Rahmi Bey",
                    "state": "İzmir", "type": "house"}, "geometry": {"coordinates": [27.1668, 38.3872]}},
]}


def _geo(nominatim, photon=None):
    """Nominatim'e her kutuda `nominatim`, Photon'a `photon` donduren sahte httpx.get."""
    calls: list[str] = []

    def fake_get(url, params=None, **kw):
        calls.append("photon" if "photon" in url else "nominatim")
        return Resp(200, photon if "photon" in url else nominatim)

    return fake_get, calls


def test_map_falls_back_to_fuzzy_search(monkeypatch):
    fake, calls = _geo([], FACULTY)       # Nominatim kelime sirasina takilir, Photon bulur
    monkeypatch.setattr(panel_tools.httpx, "get", fake)
    r = panel_tools.show_map("Dokuz Eylül Eğitim Fakültesi Buca")
    assert calls == ["nominatim", "nominatim", "photon"]
    assert r["place"].startswith("Dokuz Eylül") and r["lat"] == 38.3872   # Manisa'daki kayit elendi
    assert r["panel"]["zoom"] == panel_tools._ZOOM_DEFAULT                  # bina: yakin


def test_map_zoom_follows_place_kind():
    assert panel_tools._map_zoom("city") < panel_tools._map_zoom("suburb") < panel_tools._map_zoom("road")
    assert panel_tools._map_zoom("road") < panel_tools._map_zoom("university") == panel_tools._ZOOM_DEFAULT


@pytest.mark.parametrize("photon", [[], {"features": "bozuk"}, {"features": [None, {"properties": {"state": "İzmir"}}]}])
def test_map_survives_odd_fuzzy_answers(monkeypatch, photon):
    fake, _ = _geo([], photon)
    monkeypatch.setattr(panel_tools.httpx, "get", fake)
    assert "bulunamadi" in panel_tools.show_map("olmayan yer")["error"]


def test_map_prefers_district_over_same_named_stop(monkeypatch):
    stop = {"lat": "38.46", "lon": "27.17", "name": "Çeşme", "addresstype": "highway",
            "display_name": "Çeşme, 2140. Sokak, Bayraklı, İzmir"}
    town = {"lat": "38.32", "lon": "26.30", "name": "Çeşme", "addresstype": "town", "display_name": "Çeşme, İzmir"}

    def fake_get(url, params=None, **kw):
        return Resp(200, [stop] if params["viewbox"] == panel_tools._IZMIR_CORE_VIEWBOX else [stop, town])

    monkeypatch.setattr(panel_tools.httpx, "get", fake_get)
    assert panel_tools.show_map("Çeşme")["lon"] == 26.30        # ilce, Bayrakli'daki durak degil
    tower = {"lat": "38.4189", "lon": "27.1287", "name": "İzmir Saat Kulesi", "addresstype": "historic",
             "display_name": "İzmir Saat Kulesi, Konak, İzmir"}
    monkeypatch.setattr(panel_tools.httpx, "get", lambda url, params=None, **kw: Resp(200, [tower]))
    assert panel_tools.show_map("Saat Kulesi")["lat"] == 38.4189  # yerlesim degilse merkez kaydi


# ------------------------------------------------------------------ rota
ROUTE = {"routes": [{"distance": 9512.0, "duration": 610.0,
                     "geometry": {"coordinates": [[27.1668, 38.3872], [27.15, 38.40], [27.1428, 38.4378]]}}]}
BUCA = [{"lat": "38.3872", "lon": "27.1668", "name": "Buca", "addresstype": "town", "display_name": "Buca, İzmir"}]


def _route_get(route=ROUTE, places=None):
    seen: list[str] = []

    def fake_get(url, params=None, **kw):
        seen.append(url)
        if "routing.openstreetmap.de" in url:
            return Resp(200, route)
        q = (params or {}).get("q", "")
        return Resp(200, (places or {}).get(q, ALSANCAK if q == "Alsancak" else BUCA))

    return fake_get, seen


def test_route_draws_line_and_reports_distance(monkeypatch):
    fake, seen = _route_get()
    monkeypatch.setattr(panel_tools.httpx, "get", fake)
    r = panel_tools.show_route("Buca", "Alsancak", "yürüyerek")
    assert r["distance"] == "9,5 km" and r["duration"] == "10 dk" and r["mode"] == "yuruyus"
    assert r["origin_address"] == "Buca, İzmir"                 # model yanlis eslesmeyi gorebilsin
    assert "routed-foot" in seen[-1] and "27.1668,38.3872;27.1428,38.4378" in seen[-1]
    p = r["panel"]
    assert p["kind"] == "map" and p["title"] == "Buca → Alsancak" and "YÜRÜYÜŞ" in p["subtitle"]
    assert p["route"]["coords"][0] == [27.1668, 38.3872] and p["route"]["destination"]["label"] == "Alsancak"
    assert "fossgis_osrm_foot" in p["url"]


def test_route_requires_both_ends_and_real_places(monkeypatch):
    assert "zorunlu" in panel_tools.show_route("", "Alsancak")["error"]
    fake, _ = _route_get(places={"Atlantis": []})
    monkeypatch.setattr(panel_tools.httpx, "get", fake)
    r = panel_tools.show_route("Atlantis", "Alsancak")
    assert "Atlantis" in r["error"] and "panel" not in r


@pytest.mark.parametrize("route", [{"routes": []}, {"code": "NoRoute"}, {"routes": [{"distance": 1, "duration": 1,
                                                                                    "geometry": {"coordinates": []}}]}])
def test_route_without_path_opens_nothing(monkeypatch, route):
    fake, _ = _route_get(route=route)
    monkeypatch.setattr(panel_tools.httpx, "get", fake)
    r = panel_tools.show_route("Buca", "Alsancak")
    assert "error" in r and "panel" not in r


def test_route_line_is_thinned_but_keeps_ends():
    line = [[float(i), 0.0] for i in range(5000)]
    thin = panel_tools._thin(line)
    assert len(thin) == panel_tools._ROUTE_MAX_POINTS and thin[0] == line[0] and thin[-1] == line[-1]
    assert panel_tools._route_text(850, 30) == ("850 m", "1 dk")
    assert panel_tools._route_text(25_400, 4_000) == ("25,4 km", "1 sa 7 dk")


def test_map_control_accepts_turkish_words():
    assert panel_tools.map_control("yakınlaştır")["panel"] == {"kind": "map_control", "action": "zoom_in"}
    assert panel_tools.map_control("zoom_out")["panel"]["action"] == "zoom_out"
    assert panel_tools.map_control("haritayı döndür")["panel"]["action"] == "rotate"
    assert panel_tools.map_control("biraz uzaklaştır")["panel"]["action"] == "zoom_out"
    assert "error" in panel_tools.map_control("zıpla")


# ------------------------------------------------------------------ bilgi karti
def test_info_card_limits_and_requires_content():
    r = panel_tools.show_info("  Menemen \n tarifi  ", "## Malzemeler\n- yumurta")
    assert r["panel"] == {"kind": "info", "title": "Menemen tarifi", "subtitle": "BİLGİ KARTI",
                          "body": "## Malzemeler\n- yumurta"}
    long = panel_tools.show_info("x" * 500, "y" * 9000)
    assert len(long["panel"]["title"]) == panel_tools.INFO_TITLE_MAX
    assert len(long["panel"]["body"]) == panel_tools.INFO_BODY_MAX and "kisaltildi" in long["status"]
    assert "error" in panel_tools.show_info("", "govde") and "error" in panel_tools.show_info("baslik", "  ")


# ------------------------------------------------------------- ToolRunner
def test_runner_shows_content_and_keeps_data_for_the_model(yahoo):
    shown: list[dict] = []
    runner = ToolRunner(on_panel=lambda p: shown.append(p) or True)
    r = runner._registry["show_market"](query="borsa")
    assert shown[0]["kind"] == "chart" and "panel" not in r
    assert r["price"] == 120.0 and r["change_pct"] == 20.0     # model bunlari sesli anlatir
    assert "error" in runner._registry["show_market"](query="olmayan sirket") and len(shown) == 1


def test_runner_without_ui_never_opens_a_browser_for_content(yahoo, monkeypatch):
    monkeypatch.setattr(tool_runner, "open_website", lambda target: pytest.fail("tarayici acilmamali"))
    monkeypatch.setattr(tool_runner, "open_path", lambda target: pytest.fail("dosya acilmamali"))
    runner = ToolRunner()                                      # arayuzsuz: on_panel yok
    r = runner._registry["show_market"](query="borsa")
    assert r["price"] == 120.0 and "arayuz paneli yok" in r["status"]
    info = runner._registry["show_info"](title="Baslik", body="govde")
    assert "error" not in info and "arayuz paneli yok" in info["status"]
