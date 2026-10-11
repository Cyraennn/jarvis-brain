"""Tarayici ajani - yerel HTML sayfasiyla headless Chromium testi."""
from __future__ import annotations

import pytest

from config.settings import get_settings
from core.async_worker import get_worker
from tools import browser_tool as bt

PAGE = """<!doctype html><html><body>
<h1>Kargo Takip</h1>
<form onsubmit="event.preventDefault(); document.getElementById('out').innerText = 'Durum: ' + document.getElementById('no').value + ' dagitimda';">
  <input id="no" placeholder="Takip numarasi">
  <button type="submit">Sorgula</button>
</form>
<p id="out"></p>
<select id="sehir"><option>Izmir</option><option>Ankara</option></select>
<button onclick="this.innerText='alindi'">Satin al</button>
<input autocomplete="cc-number" placeholder="Kart">
<input type="password" placeholder="Sifre">
<a href="https://engelli.example/x">Engelli link</a>
</body></html>"""


def _ref(snapshot: dict, label: str) -> int:
    for line in snapshot["elements"].splitlines():
        if f'"{label}"' in line:
            return int(line[1:line.index("]")])
    raise AssertionError(f"{label} yok: {snapshot['elements']}")


@pytest.fixture
def page_url(tmp_path, monkeypatch):
    s = get_settings()
    patched = s.model_copy(update={"browser_headless": True, "browser_profile_dir": tmp_path / "profile",
                                   "browser_blocked_domains": ["engelli.example"]})
    monkeypatch.setattr(bt, "get_settings", lambda: patched)
    monkeypatch.setattr(bt, "_session", None)
    html = tmp_path / "kargo.html"
    html.write_text(PAGE, encoding="utf-8")
    yield html.as_uri()
    bt.browser_close()
    get_worker().shutdown()


def test_browser_flow(page_url):
    opened = bt.browser_open(page_url)
    if "error" in opened:
        pytest.skip(f"Chromium kullanilamiyor: {opened['error']}")
    snap = bt.browser_snapshot()
    assert "Kargo Takip" in snap["text"]

    res = bt.browser_type(_ref(snap, "Takip numarasi"), "TR123", submit=True)
    assert "error" not in res
    assert "Durum: TR123 dagitimda" in bt.browser_read()["text"]

    snap = bt.browser_snapshot()
    assert bt.browser_select(_ref(snap, "sehir"), "Ankara")["status"] == "secildi: Ankara"

    # guvenlik kapilari
    assert bt.browser_click(_ref(snap, "Satin al"))["blocked"]
    assert bt.browser_type(_ref(snap, "Kart"), "4111")["blocked"]
    assert bt.browser_type(_ref(snap, "Sifre"), "gizli")["blocked"]
    assert "engelli" in bt.browser_open("https://engelli.example")["error"]
    assert "bulunamadi" in bt.browser_click(9999)["error"]


def test_danger_regex():
    assert bt._DANGER_TEXT.search("Siparişi tamamla")
    assert bt._DANGER_TEXT.search("Öde")
    assert not bt._DANGER_TEXT.search("Promo code gir")
    assert not bt._DANGER_TEXT.search("Sorgula")
