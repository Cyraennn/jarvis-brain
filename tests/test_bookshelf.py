"""Kitaplik: tarama (sahte model cevaplari), birlestirme kurallari, defter, uc noktalar.

Gercek kitapliga (data/kitaplik.json) dokunmaz: depo tmp_path'e alinir.
"""
import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from core import bookshelf_store as bs
from tools import bookshelf_notebook as nb
from tools import bookshelf_scan as scan


@pytest.fixture()
def store(tmp_path):
    st = bs.BookshelfStore(tmp_path / "kitaplik.json", tmp_path / "kapaklar")
    bs.set_store(st)
    yield st
    bs.set_store(None)


def _jpeg(w=600, h=400) -> bytes:
    import cv2
    import numpy as np

    img = np.full((h, w, 3), 120, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


# ------------------------------------------------------------------ geometri
def test_tiles_cover_frame_with_overlap():
    tiles = scan.make_tiles()
    assert len(tiles) == 6
    assert min(t.x for t in tiles) == 0.0 and min(t.y for t in tiles) == 0.0
    assert max(t.x + t.w for t in tiles) == pytest.approx(1.0, abs=1e-3)
    assert max(t.y + t.h for t in tiles) == pytest.approx(1.0, abs=1e-3)
    # komsu parcalar ortusur
    a, b = tiles[0], tiles[1]
    assert b.x < a.x + a.w


def test_tiles_focus_on_shelf_region():
    tiles = scan.make_tiles({"x": 0.4, "y": 0.3, "w": 0.4, "h": 0.4})
    assert min(t.x for t in tiles) >= 0.38 and max(t.x + t.w for t in tiles) <= 0.82
    tiny = scan.make_tiles({"x": 0.5, "y": 0.5, "w": 0.01, "h": 0.01})
    assert max(t.x + t.w for t in tiny) == pytest.approx(1.0, abs=1e-3)  # cok kucukse tam kare


def test_remap_box_2d_to_full_frame():
    tile = scan.Tile(0.5, 0.5, 0.5, 0.5)
    box = scan.remap_box([0, 0, 1000, 1000], tile)
    assert box == {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}
    box = scan.remap_box([100, 200, 500, 300], tile)  # ymin, xmin, ymax, xmax
    assert box["x"] == pytest.approx(0.6) and box["y"] == pytest.approx(0.55)
    assert box["w"] == pytest.approx(0.05) and box["h"] == pytest.approx(0.2)


def test_remap_clamps_overflowing_and_rejects_bad_boxes():
    tile = scan.Tile(0.0, 0.0, 1.0, 1.0)
    box = scan.remap_box([-50, 900, 1200, 1300], tile)  # tasan kutu
    assert box["x"] + box["w"] <= 1.0 and box["y"] >= 0.0
    assert scan.remap_box([10, 10, 10, 10], tile) is None  # bos
    assert scan.remap_box("x", tile) is None
    assert scan.remap_box([1, 2, 3], tile) is None


# ------------------------------------------------------------------ model cevabi
def test_parse_invalid_json_returns_empty():
    assert scan.parse_detections("bu bir json degil", scan.Tile(0, 0, 1, 1)) == []
    assert scan.parse_detections("", scan.Tile(0, 0, 1, 1)) == []


def test_parse_handles_code_fence_and_junk_titles():
    text = """```json
[{"box_2d": [0, 0, 1000, 100], "ad": "Mülksüzler", "yazar": "Ursula K. Le Guin", "guven": 0.9},
 {"box_2d": [0, 100, 1000, 200], "ad": "null", "guven": 0.4},
 {"box_2d": [0, 200, 1000, 300], "ad": "  "},
 {"box": "kotu"}]
```"""
    dets = scan.parse_detections(text, scan.Tile(0, 0, 1, 1))
    assert len(dets) == 3
    assert dets[0]["ad"] == "Mülksüzler" and dets[0]["yazar"] == "Ursula K. Le Guin"
    assert dets[1]["ad"] is None and dets[1]["guven"] == 0.0  # "null" yazisi belirsiz sayilir
    assert dets[2]["ad"] is None


def test_merge_joins_spine_split_across_tiles():
    a = {"kutu": {"x": 0.30, "y": 0.10, "w": 0.03, "h": 0.30}, "ad": "Oblomov", "yazar": None, "guven": 0.8}
    b = {"kutu": {"x": 0.30, "y": 0.35, "w": 0.03, "h": 0.30}, "ad": None, "yazar": None, "guven": 0}
    c = {"kutu": {"x": 0.30, "y": 0.12, "w": 0.03, "h": 0.25}, "ad": "Oblomov", "yazar": "Gonçarov", "guven": 0.7}
    merged = scan.merge_detections([a, b, c])
    names = [m["ad"] for m in merged]
    assert names.count("Oblomov") == 1
    ob = next(m for m in merged if m["ad"] == "Oblomov")
    assert ob["yazar"] == "Gonçarov"


def test_merge_keeps_neighbouring_thin_spines_apart():
    a = {"kutu": {"x": 0.10, "y": 0.1, "w": 0.02, "h": 0.3}, "ad": "Davranış", "yazar": None, "guven": 0.9}
    b = {"kutu": {"x": 0.12, "y": 0.1, "w": 0.02, "h": 0.3}, "ad": "Tahıla Karşı", "yazar": None, "guven": 0.9}
    assert len(scan.merge_detections([a, b])) == 2


def test_scan_frame_with_fake_model_and_partial_failure(store):
    calls = []

    async def fake(image, prompt):
        calls.append(len(image))
        if len(calls) == 2:
            raise TimeoutError("parca zaman asimi")
        return json.dumps([{"box_2d": [100, 100, 900, 200], "ad": f"Kitap {len(calls)}", "guven": 0.9}])

    result = asyncio.run(scan.scan_frame(_jpeg(), model_call=fake))
    assert len(calls) == 6
    assert len(result["parca_hatalari"]) == 1
    assert len(result["kitaplar"]) == 5
    assert result["raf"] is not None


def test_scan_frame_all_tiles_fail_raises():
    async def fail(image, prompt):
        raise ConnectionError("internet yok")

    with pytest.raises(RuntimeError):
        asyncio.run(scan.scan_frame(_jpeg(), model_call=fail))


def test_scan_frame_empty_result(store):
    async def empty(image, prompt):
        return "[]"

    result = asyncio.run(scan.scan_frame(_jpeg(), model_call=empty))
    assert result["kitaplar"] == [] and result["raf"] is None


# ------------------------------------------------------------------ depo kurallari
def test_rescan_never_overwrites_manual_name_and_keeps_notes(store):
    stats = store.merge_scan([{"kutu": {"x": 0.1, "y": 0.1, "w": 0.03, "h": 0.3}, "ad": None}])
    assert stats == {"taninan": 0, "belirsiz": 1, "yeni": 1, "guncellenen": 0}
    book = store.books()[0]
    store.update(book["id"], ad="Davranış")  # elle adlandirma
    store.add_entry(book["id"], "Dopamin bolumu onemli", "not")
    store.merge_scan([{"kutu": {"x": 0.101, "y": 0.1, "w": 0.03, "h": 0.3}, "ad": "Yanlis Ad"}])
    books = store.books()
    assert len(books) == 1
    assert books[0]["ad"] == "Davranış" and books[0]["elle"] is True
    assert books[0]["notlar"][0]["metin"] == "Dopamin bolumu onemli"


def test_scan_places_boxless_registered_book(store):
    book, new = store.add("Mülksüzler", "Le Guin", kaynak="foto")
    assert new and book["kutu"] is None
    store.merge_scan([{"kutu": {"x": 0.5, "y": 0.2, "w": 0.03, "h": 0.3}, "ad": "MÜLKSÜZLER"}])
    books = store.books()
    assert len(books) == 1 and books[0]["kutu"] is not None


def test_add_deduplicates(store):
    a, new_a = store.add("Tahıla Karşı", "James C. Scott")
    b, new_b = store.add("tahila karsi")
    assert new_a and not new_b and a["id"] == b["id"]


def test_layout_links_unnamed_box_to_registered_book(store):
    store.merge_scan([{"kutu": {"x": 0.2, "y": 0.1, "w": 0.03, "h": 0.3}, "ad": None}])
    unnamed = store.books()[0]
    named, _ = store.add("Oblomov", "Gonçarov")
    store.add_entry(named["id"], "tembellik uzerine", "not")
    snap = store.save_layout([{"id": unnamed["id"], "link": named["id"], "kutu": unnamed["kutu"]}])
    assert len(snap["books"]) == 1
    only = snap["books"][0]
    assert only["id"] == named["id"] and only["kutu"] is not None and only["notlar"]


def test_layout_delete_rules(store):
    store.merge_scan([{"kutu": {"x": 0.2, "y": 0.1, "w": 0.03, "h": 0.3}, "ad": None}])
    scanned = store.books()[0]
    named, _ = store.add("Oblomov", kutu={"x": 0.4, "y": 0.1, "w": 0.03, "h": 0.3})
    snap = store.save_layout([], [scanned["id"], named["id"]])
    assert [b["id"] for b in snap["books"]] == [named["id"]]  # adli kitap kutusuz kalir
    assert snap["books"][0]["kutu"] is None


def test_update_validates(store):
    book, _ = store.add("Oblomov")
    with pytest.raises(ValueError):
        store.update(book["id"], durum="yarim")
    assert store.update(book["id"], durum="okunuyor", sayfa="120")["sayfa"] == 120


def test_find_fuzzy(store):
    store.add("Otostopçunun Galaksi Rehberi", "Douglas Adams")
    assert store.find("otostopcunun galaksi rehberi")["yazar"] == "Douglas Adams"
    assert store.find("tamamen alakasiz") is None


def test_persists_utf8(store, tmp_path):
    store.add("Şeker Portakalı", "José Mauro de Vasconcelos")
    raw = (tmp_path / "kitaplik.json").read_text(encoding="utf-8")
    assert "Şeker Portakalı" in raw
    again = bs.BookshelfStore(tmp_path / "kitaplik.json")
    assert again.books()[0]["ad"] == "Şeker Portakalı"


# ------------------------------------------------------------------ defter
def test_notebook_unknown_book_is_not_invented(store):
    book, _ = store.add("Hic Var Olmamis Kitap 9000")

    async def fake(system, prompt):
        return '{"bilinmiyor": true}'

    out = asyncio.run(nb.write_notebook(book["id"], store=store, text_call=fake))
    assert out["defter"]["bilinmiyor"] is True


def test_notebook_filters_similar_to_own_library_and_strips_quotes(store):
    book, _ = store.add("Mülksüzler", "Ursula K. Le Guin")
    store.add("Karanlığın Sol Eli", "Ursula K. Le Guin")

    async def fake(system, prompt):
        assert "KULLANICININ KITAPLIGI" in prompt and "Karanlığın Sol Eli" in prompt
        return json.dumps({
            "bilinmiyor": False, "ozet": "Iki gezegen arasinda bir fizikci. \"" + "a" * 80 + "\"",
            "ana_fikirler": ["x", "y", "z", "w"], "temalar": ["utopya"],
            "benzerler": ["Karanlığın Sol Eli", "Dune", "Mülksüzler"],
        })

    out = asyncio.run(nb.write_notebook(book["id"], store=store, text_call=fake))
    d = out["defter"]
    assert d["benzerler"] == ["Karanlığın Sol Eli"]  # kitaplikta olmayan Dune ve kendisi elendi
    assert "a" * 80 not in d["ozet"]


# ------------------------------------------------------------------ HTTP
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def http(tmp_path, store, monkeypatch):
    from web.console_server import ConsoleServer

    monkeypatch.setattr(nb, "enrich_in_background", lambda *a, **k: None)
    port = _free_port()
    srv = ConsoleServer(outbox_path=tmp_path / "outbox.txt", inbox_path=tmp_path / "inbox.txt",
                        port=port, bind="127.0.0.1", token="s3cret-token")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield srv, port
    srv.stop()


def _req(port, path, *, data=None, ctype="application/json", key="s3cret-token"):
    sep = "&" if "?" in path else "?"
    url = f"http://127.0.0.1:{port}{path}" + (f"{sep}key={key}" if key else "")
    body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
    r = urllib.request.Request(url, data=body, headers={"Content-Type": ctype} if body is not None else {})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def test_http_requires_auth(http):
    _, port = http
    assert _req(port, "/api/kitaplik", key="")[0] == 401
    assert _req(port, "/el", key="yanlis")[0] == 401


def test_http_add_note_and_list(http):
    _, port = http
    code, out = _req(port, "/api/kitaplik/kitap", data={"islem": "ekle", "ad": "Oblomov"})
    assert code == 200 and out["yeni"]
    bid = out["kitap"]["id"]
    assert _req(port, "/api/kitaplik/kitap", data={"islem": "not", "id": bid, "metin": "s.120"})[0] == 200
    code, snap = _req(port, "/api/kitaplik")
    assert code == 200 and snap["books"][0]["notlar"][0]["metin"] == "s.120"
    assert _req(port, "/api/kitaplik/kitap", data={"islem": "uydur", "id": bid})[0] == 400


def test_http_json_body_limit_413(http):
    _, port = http
    big = b'{"text": "' + b"a" * (2 * 1024 * 1024 + 10) + b'"}'
    code, _ = _req(port, "/api/say", data=big)
    assert code == 413


def test_http_scan_rejects_non_image(http):
    _, port = http
    code, out = _req(port, "/api/kitaplik/tara", data=b"not an image", ctype="image/jpeg")
    assert code == 400


def test_http_say_source_el(http, tmp_path):
    _, port = http
    code, out = _req(port, "/api/say", data={"text": "kahve yap", "source": "EL"})
    assert code == 200 and out["source"] == "el"
    assert (tmp_path / "outbox.txt").read_text(encoding="utf-8").strip() == "[EL] kahve yap"
    assert _req(port, "/api/say", data={"text": "x", "source": "HACK"})[0] == 400


def test_http_el_page_and_open_book_state(http, store):
    _, port = http
    book, _ = store.add("Oblomov")
    assert _req(port, "/api/el/durum", data={"kitap_id": book["id"], "sayfa": 2})[0] == 200
    code, state = _req(port, "/api/el/durum")
    assert code == 200 and state["kitap"]["ad"] == "Oblomov"


def test_http_models_route_rejects_traversal(http):
    _, port = http
    assert _req(port, "/models/..%5Csecret.task", key="")[0] == 404
    assert _req(port, "/models/nope.exe", key="")[0] == 404


# ------------------------------------------------------------------ Calibre
def _fake_calibre(lib):
    import sqlite3

    lib.mkdir()
    con = sqlite3.connect(lib / "metadata.db")
    con.executescript("""
    CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, path TEXT, has_cover BOOL, series_index REAL);
    CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE books_authors_link (book INTEGER, author INTEGER);
    CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE books_tags_link (book INTEGER, tag INTEGER);
    CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE books_series_link (book INTEGER, series INTEGER);
    CREATE TABLE comments (book INTEGER, text TEXT);
    CREATE TABLE identifiers (book INTEGER, type TEXT, val TEXT);
    CREATE TABLE data (book INTEGER, format TEXT, name TEXT);
    INSERT INTO books VALUES (1, 'Dune', 'Frank Herbert/Dune (1)', 1, 1.0), (2, 'Mülksüzler', 'Le Guin/Mulksuzler (2)', 0, 1.0);
    INSERT INTO authors VALUES (1, 'Frank Herbert'), (2, 'Ursula K. Le Guin');
    INSERT INTO books_authors_link VALUES (1, 1), (2, 2);
    INSERT INTO tags VALUES (1, 'bilimkurgu');
    INSERT INTO books_tags_link VALUES (1, 1), (2, 1);
    INSERT INTO series VALUES (1, 'Dune');
    INSERT INTO books_series_link VALUES (1, 1);
    INSERT INTO comments VALUES (1, '<p>Çöl gezegeni <b>Arrakis</b>.</p>');
    INSERT INTO data VALUES (1, 'EPUB', 'Dune - Frank Herbert'), (1, 'PDF', 'Dune - Frank Herbert');
    """)
    con.commit()
    con.close()
    folder = lib / "Frank Herbert" / "Dune (1)"
    folder.mkdir(parents=True)
    (folder / "Dune - Frank Herbert.epub").write_bytes(b"epub")
    (folder / "cover.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 2000)


def test_calibre_sync_imports_and_dedupes(store, tmp_path, monkeypatch):
    from tools import calibre_library as cl

    lib = tmp_path / "Calibre Library"
    _fake_calibre(lib)
    monkeypatch.setenv("CYRAEN_CALIBRE_LIBRARY", str(lib))
    store.add("Dune")  # fiziksel kitap zaten kayitli
    out = cl.sync(store)
    assert out["toplam"] == 2 and out["eklenen"] == 1
    books = {b["ad"]: b for b in store.books()}
    assert len(books) == 2
    dune = books["Dune"]
    assert dune["calibre"]["formatlar"][0] == "EPUB"
    assert "Arrakis" in dune["calibre"]["aciklama"] and "<b>" not in dune["calibre"]["aciklama"]
    assert dune["calibre"]["seri"] == "Dune #1"
    assert dune["kapak"]  # Calibre kapagi kullanildi
    assert cl.sync(store)["eklenen"] == 0  # tekrar esitleme cogaltmaz
    assert cl.book_file(1).suffix == ".epub"
    assert cl.book_file(1, "PDF").suffix == ".epub"  # PDF dosyasi diskte yok -> siradaki


def test_calibre_missing_library(store, monkeypatch, tmp_path):
    from tools import calibre_library as cl

    monkeypatch.setenv("CYRAEN_CALIBRE_LIBRARY", str(tmp_path / "yok"))
    monkeypatch.setattr(cl, "find_library", lambda: None)
    assert "error" in cl.sync(store)


def test_notebook_prompt_includes_calibre_description(store):
    book, _ = store.add("Dune", "Frank Herbert")
    store.link_calibre(book["id"], {"calibre_id": 1, "aciklama": "Çöl gezegeni Arrakis.", "etiketler": ["bk"]})
    seen = {}

    async def fake(system, prompt):
        seen["p"] = prompt
        return '{"bilinmiyor": true}'

    asyncio.run(nb.write_notebook(book["id"], store=store, text_call=fake))
    assert "Arrakis" in seen["p"] and "Calibre" in seen["p"]


# ------------------------------------------------------------------ elde tutulan kitap
def test_unnamed_scan_does_not_set_shelf_region(store):
    async def junk(image, prompt):
        return json.dumps([{"box_2d": [0, 0, 900, 900], "ad": None}, {"box_2d": [0, 0, 500, 300], "ad": None},
                           {"box_2d": [500, 500, 900, 900], "ad": None}])

    result = asyncio.run(scan.scan_frame(_jpeg(), model_call=junk))
    assert result["kitaplar"] == [] and result["raf"] is None
    store.set_shelf(raf={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
    store.merge_scan(result["kitaplar"], raf=result["raf"])
    assert store.snapshot()["raf"]["w"] == 0.5  # onceki bolge korunur


def test_read_held_book_parses_and_rejects():
    async def ok(image, prompt):
        assert "KITAP" in prompt
        return '{"kitap_var": true, "ad": "Kürk Mantolu Madonna", "yazar": "Sabahattin Ali", "guven": 0.92}'

    async def none(image, prompt):
        return '{"kitap_var": false, "ad": null}'

    r = asyncio.run(scan.read_held_book(_jpeg(), model_call=ok))
    assert r["ad"] == "Kürk Mantolu Madonna" and r["guven"] == 0.92
    r = asyncio.run(scan.read_held_book(_jpeg(), model_call=none))
    assert r["ad"] is None and r["kitap_var"] is False and r["guven"] == 0.0


def test_http_held_book_adds_to_library(http, store, monkeypatch):
    _, port = http

    async def fake(jpeg, model_call=None):
        return {"kitap_var": True, "ad": "Oblomov", "yazar": "Gonçarov", "guven": 0.9, "okunan_metin": ""}

    monkeypatch.setattr(scan, "read_held_book", fake)
    code, out = _req(port, "/api/kitaplik/eldeki", data=_jpeg(), ctype="image/jpeg")
    assert code == 200 and out["durum"] == "eklendi" and out["kitap"]["kaynak"] == "kamera"
    code, out = _req(port, "/api/kitaplik/eldeki", data=_jpeg(), ctype="image/jpeg")
    assert out["durum"] == "zaten_vardi"
