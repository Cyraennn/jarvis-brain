"""Icerik paneli araclari - agsiz testler. Model kimlik/adres/yol uyduramaz: panel yalnizca
aracin kendi buldugu ve dogruladigi icerik icin acilir."""
from __future__ import annotations

import os

import pytest

from tools import panel_tools, tool_runner
from tools.tool_declarations import build_declarations
from tools.tool_runner import ToolRunner

PANEL_TOOLS = {"show_video", "show_wikipedia", "show_document", "show_website", "show_spotify", "close_panel"}
REAL, BLOCKED = "dQw4w9WgXcQ", "blockedVid1"


class Resp:
    def __init__(self, status: int, data=None, text: str = "") -> None:
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        if self._data is None:
            raise ValueError("json yok")
        return self._data


@pytest.fixture()
def oembed(monkeypatch):
    """YouTube oEmbed: REAL var, BLOCKED gomme kapali, digerleri yok."""
    def fake(video_id: str):
        if video_id == REAL:
            return "ok", {"title": "Gercek Video", "author_name": "Kanal"}
        return ("blocked", {}) if video_id == BLOCKED else ("missing", {})

    monkeypatch.setattr(panel_tools, "_oembed", fake)


@pytest.fixture()
def docs(tmp_path, monkeypatch):
    root = tmp_path / "belgeler"
    (root / "alt").mkdir(parents=True)
    (root / "Kira Sözleşmesi.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (root / "alt" / "notlar.md").write_text("merhaba", encoding="utf-8")
    (root / "rapor 2025.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "rapor 2026.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "gizli.exe").write_bytes(b"MZ")
    (root / "bos.txt").write_bytes(b"")
    outside = tmp_path / "disarida.pdf"
    outside.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(panel_tools, "doc_roots", lambda: [root.resolve()])
    return root, outside


def test_declared_and_registered():
    declared = {d.name for d in build_declarations()}
    assert PANEL_TOOLS <= declared
    assert PANEL_TOOLS <= set(ToolRunner().tool_names)


# ------------------------------------------------------------------ video
@pytest.mark.parametrize("text,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", REAL),
    ("https://youtu.be/dQw4w9WgXcQ", REAL),
    ("youtube.com/shorts/dQw4w9WgXcQ", REAL),
    ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", REAL),
    ("galatasaray", None),                                   # 11 karakterlik kelime kimlik sayilmaz
    ("dQw4w9WgXcQ", None),                                   # ciplak kimlik: model dogrulamayi atlayamaz
    ("https://evil.example/watch?v=dQw4w9WgXcQ", None),
    ("https://www.youtube.com/watch?v=kisa", None),
])
def test_video_id_from(text, expected):
    assert panel_tools.video_id_from(text) == expected


def test_video_search_opens_first_verified(oembed, monkeypatch):
    monkeypatch.setattr(panel_tools, "_search_video_ids", lambda q: ["yokyokyok01", BLOCKED, REAL])
    r = panel_tools.show_video("bir video")
    assert r["panel"] == {"kind": "video", "video_id": REAL, "title": "Gercek Video", "subtitle": "Kanal",
                          "url": f"https://www.youtube.com/watch?v={REAL}"}
    assert r["title"] == "Gercek Video" and r["channel"] == "Kanal"


def test_fabricated_video_link_is_rejected(oembed, monkeypatch):
    monkeypatch.setattr(panel_tools, "_search_video_ids", lambda q: pytest.fail("link verildiyse arama yapilmaz"))
    r = panel_tools.show_video("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    assert "error" in r and "panel" not in r


def test_embed_blocked_video_does_not_open(oembed, monkeypatch):
    monkeypatch.setattr(panel_tools, "_search_video_ids", lambda q: [BLOCKED])
    r = panel_tools.show_video("s sport ozet")
    assert "error" in r and "panel" not in r and BLOCKED in r["url"]


def test_video_not_found_and_empty(oembed, monkeypatch):
    monkeypatch.setattr(panel_tools, "_search_video_ids", lambda q: [])
    assert "error" in panel_tools.show_video("hicbir sey")
    assert "error" in panel_tools.show_video("  ")


# -------------------------------------------------------------- wikipedia
def _wiki_get(pages: dict[str, dict], search: dict[str, str]):
    def fake_get(url, params=None, **_kw):
        if "/page/summary/" in url:
            lang = url.split("//")[1].split(".")[0]
            data = pages.get(f"{lang}:{url.rsplit('/', 1)[1]}")
            return Resp(200, data) if data else Resp(404, {"type": "not_found"})
        lang = url.split("//")[1].split(".")[0]
        hit = search.get(f"{lang}:{params['search']}")
        return Resp(200, [params["search"], [hit] if hit else []])
    return fake_get


def _page(lang: str, title: str, **extra):
    slug = title.replace(" ", "_")
    return {"title": title, "type": "standard", "extract": f"{title} hakkinda ozet.", "description": "aciklama",
            "content_urls": {"mobile": {"page": f"https://{lang}.m.wikipedia.org/wiki/{slug}"}}, **extra}


def test_wikipedia_direct_hit(monkeypatch):
    monkeypatch.setattr(panel_tools.httpx, "get", _wiki_get({"tr:Ankara": _page("tr", "Ankara")}, {}))
    r = panel_tools.show_wikipedia("Ankara")
    assert r["title"] == "Ankara" and r["language"] == "tr" and r["summary"] == "Ankara hakkinda ozet."
    assert r["panel"] == {"kind": "wiki", "url": "https://tr.m.wikipedia.org/wiki/Ankara", "title": "Ankara",
                          "subtitle": "Wikipedia · TR"}


def test_wikipedia_uses_search_then_english(monkeypatch):
    pages = {"en:Claude_Shannon": _page("en", "Claude Shannon")}
    monkeypatch.setattr(panel_tools.httpx, "get", _wiki_get(pages, {"en:shannon": "Claude Shannon"}))
    r = panel_tools.show_wikipedia("shannon")
    assert r["title"] == "Claude Shannon" and r["language"] == "en"   # baslik modelden degil Wikipedia'dan


def test_wikipedia_missing_and_foreign_url(monkeypatch):
    monkeypatch.setattr(panel_tools.httpx, "get", _wiki_get({}, {}))
    r = panel_tools.show_wikipedia("olmayan sayfa")
    assert "error" in r and "panel" not in r
    evil = _page("tr", "Sahte")
    evil["content_urls"] = {"mobile": {"page": "https://evil.example/wiki/Sahte"}}
    monkeypatch.setattr(panel_tools.httpx, "get", _wiki_get({"tr:Sahte": evil, "en:Sahte": evil}, {}))
    assert "error" in panel_tools.show_wikipedia("Sahte")


def test_wikipedia_disambiguation_note(monkeypatch):
    pages = {"tr:Merkür": _page("tr", "Merkür", type="disambiguation")}
    monkeypatch.setattr(panel_tools.httpx, "get",
                        lambda url, params=None, **kw: Resp(200, pages["tr:Merkür"]) if "summary" in url else Resp(404))
    assert "note" in panel_tools.show_wikipedia("Merkür")


# ------------------------------------------------------------------ belge
def test_document_found_by_name(docs):
    root, _ = docs
    r = panel_tools.show_document("kira sozlesmesi belgesini")     # Turkce harf + dolgu kelime duyarsiz
    assert r["name"] == "Kira Sözleşmesi.pdf" and r["type"] == "pdf"
    assert r["panel"]["kind"] == "doc" and r["panel"]["doc_type"] == "pdf"
    assert os.path.samefile(r["panel"]["path"], root / "Kira Sözleşmesi.pdf")
    assert panel_tools.show_document("notlar")["panel"]["doc_type"] == "metin"     # alt klasor


def test_document_ambiguous_does_not_open(docs):
    r = panel_tools.show_document("rapor")
    assert "panel" not in r and {m["name"] for m in r["matches"]} == {"rapor 2025.pdf", "rapor 2026.pdf"}
    chosen = next(m["path"] for m in r["matches"] if m["name"] == "rapor 2026.pdf")
    assert panel_tools.show_document(chosen)["name"] == "rapor 2026.pdf"           # secilen yol ile acilir
    assert panel_tools.show_document("rapor 2025")["name"] == "rapor 2025.pdf"     # tam ad tek eslesme


def test_document_rejections(docs):
    root, outside = docs
    for query in ("olmayan belge", str(root / "yok.pdf"), str(root / "gizli.exe"), str(root / "bos.txt"),
                  str(outside), str(root / ".." / "disarida.pdf"), "gizli", "  "):
        r = panel_tools.show_document(query)
        assert "error" in r and "panel" not in r, query


# -------------------------------------------------------------------- site
@pytest.mark.parametrize("target,url", [
    ("github.com", "https://github.com"),
    ("gmail", "https://mail.google.com"),
    ("https://example.org/a?b=1", "https://example.org/a?b=1"),
    ("hava durumu izmir", "https://www.google.com/search?q=hava+durumu+izmir"),
])
def test_website_resolves(target, url):
    r = panel_tools.show_website(target)
    assert r["panel"]["kind"] == "web" and r["panel"]["url"] == url


@pytest.mark.parametrize("target", ["javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,x",
                                    "chrome://settings", "", "https://"])
def test_website_rejects_non_http(target):
    r = panel_tools.show_website(target)
    assert "error" in r and "panel" not in r


# ----------------------------------------------------------------- spotify
def test_spotify_card(monkeypatch):
    monkeypatch.setattr(panel_tools, "spotify_enabled", lambda: False)
    assert "error" in panel_tools.show_spotify()
    monkeypatch.setattr(panel_tools, "spotify_enabled", lambda: True)
    monkeypatch.setattr(panel_tools, "spotify_playback_state", lambda: {
        "ok": True, "active": True, "playing": True, "track": "Danza Kuduro", "device": "SEZAI-PC",
        "image": "https://i.scdn.co/x", "progress_ms": 1000, "duration_ms": 9000})
    r = panel_tools.show_spotify()
    assert r["panel"]["kind"] == "spotify" and r["track"] == "Danza Kuduro" and "image" not in r


# ------------------------------------------------------------- ToolRunner
def test_runner_forwards_verified_payload_and_strips_it(oembed, monkeypatch):
    monkeypatch.setattr(panel_tools, "_search_video_ids", lambda q: [REAL])
    shown: list[dict] = []
    runner = ToolRunner(on_panel=lambda p: shown.append(p) or True)
    r = runner._registry["show_video"](query="bir video")
    assert shown == [{"kind": "video", "video_id": REAL, "title": "Gercek Video", "subtitle": "Kanal",
                      "url": f"https://www.youtube.com/watch?v={REAL}"}]
    assert "panel" not in r and "error" not in r                 # yuk modele gitmez
    assert runner._registry["close_panel"]() == {"status": "panel kapatildi"}
    assert shown[-1] == {"kind": "close"}


def test_runner_never_shows_unverified(oembed, monkeypatch):
    monkeypatch.setattr(panel_tools, "_search_video_ids", lambda q: [])
    shown: list[dict] = []
    runner = ToolRunner(on_panel=lambda p: shown.append(p) or True)
    assert "error" in runner._registry["show_video"](query="https://youtu.be/aaaaaaaaaaa")
    assert "error" in runner._registry["show_website"](target="javascript:alert(1)")
    assert shown == []


def test_runner_falls_back_to_external_without_ui(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(tool_runner, "open_website", lambda target: opened.append(target) or {"status": "acildi"})
    r = ToolRunner()._registry["show_website"](target="github.com")    # arayuzsuz: on_panel yok
    assert opened == ["https://github.com"] and "varsayilan uygulamada" in r["status"]


def test_spotify_play_opens_card(monkeypatch):
    monkeypatch.setattr(tool_runner, "spotify_play",
                        lambda **kw: {"ok": True, "playing": "x", "device": "SEZAI-PC"} if kw["query"] else {"error": "yok"})
    shown: list[dict] = []
    runner = ToolRunner(on_panel=lambda p: shown.append(p) or True)
    assert runner._registry["spotify_play"](query="danza")["ok"]
    assert shown == [{"kind": "spotify", "title": "Spotify", "subtitle": "SEZAI-PC"}]
    assert "error" in runner._registry["spotify_play"](query="")
    assert len(shown) == 1
