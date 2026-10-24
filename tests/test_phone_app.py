"""Telefon uygulamasi icin PC tarafi: eylem kanali, telefon araclari, dosya alisverisi,
uzaktan ekran kilidi ve web konsolu uclari (ag yok: yerel sunucu + sahte telefon)."""
import io
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from web import phone_files
from web.console_server import ConsoleServer
from web.event_bus import BUS, EventBus
from web.phone_link import PhoneLink

TOKEN = "s3cret-token"


# ------------------------------------------------------------ eylem kanali
def _answer_next(link: PhoneLink, reply: dict, delay: float = 0.05) -> threading.Thread:
    """Sahte telefon: veriyolundaki bir sonraki phone_action'a yanit verir."""
    q = BUS.subscribe()

    def run():
        try:
            for _ in range(200):
                while q:
                    evt = q.popleft()
                    if evt["kind"] == "phone_action":
                        time.sleep(delay)
                        link.resolve(evt["data"]["id"], reply)
                        return
                time.sleep(0.01)
        finally:
            BUS.unsubscribe(q)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_request_without_phone_fails_fast():
    link = PhoneLink()
    start = time.monotonic()
    assert "error" in link.request("call", {"contact": "Annem"})
    assert time.monotonic() - start < 0.5


def test_request_returns_phone_reply():
    link = PhoneLink()
    link.attach()
    _answer_next(link, {"status": "ok", "result": {"lat": 38.4, "lon": 27.1}})
    assert link.request("location", {}, timeout=3) == {"status": "ok", "result": {"lat": 38.4, "lon": 27.1}}


def test_request_times_out_and_late_reply_is_rejected():
    link = PhoneLink()
    link.attach()
    q = BUS.subscribe()
    try:
        out = link.request("call", {"contact": "x"}, timeout=0.2)
        assert "yanit vermedi" in out["error"]
        req_id = next(e["data"]["id"] for e in list(q) if e["kind"] == "phone_action")
        assert link.resolve(req_id, {"status": "ok"}) is False
    finally:
        BUS.unsubscribe(q)


def test_detach_counts_clients():
    link = PhoneLink()
    link.attach()
    link.attach()
    link.detach()
    assert link.connected
    link.detach()
    link.detach()  # fazladan detach eksiye dusmez
    assert not link.connected


# ------------------------------------------------------------ telefon araclari
def test_phone_tools_validate_before_sending(monkeypatch):
    from tools import phone_tools

    sent = []
    monkeypatch.setattr(phone_tools.PHONE, "request", lambda name, args=None, timeout=0: sent.append(name) or {})
    assert "error" in phone_tools.phone_call("  ")
    assert "error" in phone_tools.send_sms("Annem", "")
    assert "error" in phone_tools.set_alarm("25:00")
    assert "error" in phone_tools.set_alarm("yedi")
    assert "error" in phone_tools.set_timer(0)
    assert sent == []
    phone_tools.set_alarm("7.05", "okul")
    phone_tools.set_timer(0.5)
    assert sent == ["alarm", "timer"]


def test_set_alarm_payload(monkeypatch):
    from tools import phone_tools

    calls = []
    monkeypatch.setattr(phone_tools.PHONE, "request", lambda name, args=None, timeout=0: calls.append(args) or {})
    phone_tools.set_alarm("06:45")
    assert calls == [{"hour": 6, "minute": 45, "label": "CYRAEN"}]


def test_current_location_parses_reply(monkeypatch):
    from tools import phone_tools

    monkeypatch.setattr(phone_tools, "phone_location", lambda: {"status": "ok", "result": {"lat": "38.5", "lon": 27.2}})
    assert phone_tools.current_location() == (38.5, 27.2)
    monkeypatch.setattr(phone_tools, "phone_location", lambda: {"error": "bagli degil"})
    assert phone_tools.current_location() is None


def test_send_file_to_phone_copies_into_outbox(tmp_path, monkeypatch):
    from tools import phone_tools

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(phone_files, "PHONE_OUTBOX", outbox)
    src = tmp_path / "rapor.pdf"
    src.write_bytes(b"%PDF")
    out = phone_tools.send_file_to_phone(str(src))
    assert out["name"] == "rapor.pdf" and (outbox / "rapor.pdf").read_bytes() == b"%PDF"
    again = phone_tools.send_file_to_phone(str(src))
    assert again["name"] == "rapor (2).pdf"
    assert "error" in phone_tools.send_file_to_phone(str(tmp_path / "yok.txt"))


# ------------------------------------------------------------ dosyalar
@pytest.mark.parametrize("raw,clean", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Windows\\win.ini", "win.ini"),
    ('a<b>:c?.txt', "a_b__c_.txt"),
    ("...", None),
])
def test_safe_name(raw, clean):
    name = phone_files.safe_name(raw)
    if clean is None:
        assert name.startswith("dosya-")
    else:
        assert name == clean


def test_save_upload_removes_partial_file(tmp_path):
    with pytest.raises(ValueError):
        phone_files.save_upload(io.BytesIO(b"abc"), 10, "x.bin", tmp_path)
    assert list(tmp_path.iterdir()) == []
    saved = phone_files.save_upload(io.BytesIO(b"abc"), 3, "x.bin", tmp_path)
    assert saved.read_bytes() == b"abc"


def test_outbox_file_blocks_escape(tmp_path):
    (tmp_path / "ok.txt").write_text("x")
    (tmp_path.parent / "secret.txt").write_text("s")
    assert phone_files.outbox_file("ok.txt", tmp_path) == (tmp_path / "ok.txt").resolve()
    assert phone_files.outbox_file("../secret.txt", tmp_path) is None
    assert phone_files.outbox_file("", tmp_path) is None
    assert phone_files.outbox_file("yok.txt", tmp_path) is None


# ------------------------------------------------------------ veriyolu paneli
def test_bus_keeps_last_panel_for_late_phone():
    bus = EventBus()
    bus.push("panel", {"kind": "map", "lat": 1})
    bus.push("panel", {"kind": "map_control", "action": "zoom_in"})
    assert bus.snapshot()["panel"] == {"kind": "map", "lat": 1}
    bus.push("panel", {"kind": "close"})
    assert bus.snapshot()["panel"] is None


def test_observer_strips_local_path_from_panel(monkeypatch):
    from ui import qt_observer

    pushed = []
    monkeypatch.setattr(qt_observer.BUS, "push", lambda kind, data=None: pushed.append((kind, data)))
    obs = qt_observer.QtEngineObserver.__new__(qt_observer.QtEngineObserver)
    monkeypatch.setattr(obs, "_emit", lambda *a: None, raising=False)
    obs.on_panel({"kind": "doc", "path": "C:/gizli/rapor.pdf", "title": "rapor.pdf"})
    assert pushed == [("panel", {"kind": "doc", "title": "rapor.pdf"})]


# ------------------------------------------------------------ rota: konumum
def test_route_from_my_location_uses_phone_gps(monkeypatch):
    from tools import panel_tools, phone_tools

    monkeypatch.setattr(phone_tools, "current_location", lambda: (38.39, 27.17))
    monkeypatch.setattr(panel_tools, "_geocode",
                        lambda p: {"lat": 38.43, "lon": 27.14, "name": "Alsancak", "address": "Konak", "kind": "suburb"})

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"routes": [{"distance": 6000, "duration": 600,
                                "geometry": {"coordinates": [[27.17, 38.39], [27.14, 38.43]]}}]}

    seen = {}
    monkeypatch.setattr(panel_tools.httpx, "get", lambda url, **kw: seen.setdefault("url", url) and R())
    out = panel_tools.show_route("buradan", "Alsancak")
    assert "error" not in out, out
    assert "27.17,38.39;27.14,38.43" in seen["url"]
    assert out["panel"]["route"]["origin"]["label"] == "Konumunuz"


def test_route_from_my_location_without_phone(monkeypatch):
    from tools import panel_tools, phone_tools

    monkeypatch.setattr(phone_tools, "current_location", lambda: None)
    out = panel_tools.show_route("konumum", "Alsancak")
    assert "Telefon konumu" in out["error"] and "panel" not in out


# ------------------------------------------------------------ web konsolu uclari
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(tmp_path, **kw):
    port = _free_port()
    srv = ConsoleServer(outbox_path=tmp_path / "outbox.txt", inbox_path=tmp_path / "inbox.txt",
                        port=port, bind="127.0.0.1", token=TOKEN, **kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return srv, port


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(phone_files, "PHONE_INBOX", tmp_path / "inbox")
    monkeypatch.setattr(phone_files, "PHONE_OUTBOX", tmp_path / "phone_out")
    srv, port = _start(tmp_path)
    yield srv, port, tmp_path
    srv.stop()


def _call(port, path, data=None, raw=None, headers=None):
    url = f"http://127.0.0.1:{port}{path}{'&' if '?' in path else '?'}key={TOKEN}"
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_phone_result_resolves_pending(server):
    from web.phone_link import PHONE

    _, port, _ = server
    code, body, _ = _call(port, "/api/phone-result", {"id": "yok", "ok": True})
    assert code == 404
    PHONE.attach()
    try:
        q = BUS.subscribe()
        result = {}
        t = threading.Thread(target=lambda: result.update(PHONE.request("status", {}, timeout=3)))
        t.start()
        req_id = None
        for _ in range(100):
            req_id = next((e["data"]["id"] for e in list(q) if e["kind"] == "phone_action"), None)
            if req_id:
                break
            time.sleep(0.02)
        BUS.unsubscribe(q)
        code, _, _ = _call(port, "/api/phone-result", {"id": req_id, "ok": True, "result": {"battery": 80}})
        t.join(3)
        assert code == 200 and result == {"status": "ok", "result": {"battery": 80}}
    finally:
        PHONE.detach()


def test_upload_and_download_roundtrip(server):
    _, port, tmp = server
    code, body, _ = _call(port, "/api/files/upload?name=foto%201.jpg", raw=b"JPEGDATA",
                          headers={"Content-Type": "application/octet-stream"})
    assert code == 200 and json.loads(body)["name"] == "foto 1.jpg"
    assert (tmp / "inbox" / "foto 1.jpg").read_bytes() == b"JPEGDATA"
    assert "[TELEFON DOSYA]" in (tmp / "outbox.txt").read_text(encoding="utf-8")

    (tmp / "phone_out").mkdir()
    (tmp / "phone_out" / "not.txt").write_bytes(b"merhaba")
    code, body, _ = _call(port, "/api/files")
    assert [f["name"] for f in json.loads(body)["files"]] == ["not.txt"]
    code, body, headers = _call(port, "/api/files/get?name=not.txt")
    assert code == 200 and body == b"merhaba"
    code, _, _ = _call(port, "/api/files/get?name=..%2Foutbox.txt")
    assert code == 404


def test_upload_requires_token(server):
    _, port, tmp = server
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/files/upload?name=x", data=b"x")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 401
    assert not (tmp / "inbox").exists()


def test_remote_desktop_is_off_by_default(server):
    _, port, _ = server
    assert _call(port, "/api/screen/stream")[0] == 403
    assert _call(port, "/api/remote/input", {"type": "tap", "x": 0.5, "y": 0.5})[0] == 403


def test_remote_input_maps_to_keyboard_tools(tmp_path, monkeypatch):
    from tools import keyboard_input

    clicks = []
    monkeypatch.setattr(keyboard_input, "click_at",
                        lambda x, y, button="left", double=False: clicks.append((x, y, button, double)) or {"status": "ok"})
    srv, port = _start(tmp_path, remote_desktop=True)
    try:
        code, body, _ = _call(port, "/api/remote/input", {"type": "right", "x": 0.25, "y": 2})
        assert code == 200 and clicks == [(250.0, 1000.0, "right", False)]
        code, body, _ = _call(port, "/api/remote/input", {"type": "tap"})
        assert "error" in json.loads(body)
    finally:
        srv.stop()


def test_phone_sse_marks_phone_connected(server):
    from web.phone_link import PHONE

    _, port, _ = server
    before = PHONE.connected
    url = f"http://127.0.0.1:{port}/api/events?client=phone&key={TOKEN}"
    resp = urllib.request.urlopen(url, timeout=5)
    try:
        assert resp.readline().startswith(b"data: ")
        assert PHONE.connected
    finally:
        resp.close()
    assert before is False


# ------------------------------------------------------------ QR eslestirme
def test_pair_page_is_local_only_and_contains_link(server, monkeypatch):
    from web import console_server

    srv, port, _ = server
    monkeypatch.setattr(console_server, "_tailscale_ip", lambda: "100.1.2.3")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/pair", timeout=5) as r:
        page = r.read().decode("utf-8")
    assert "100.1.2.3" in page and "<svg" in page
    assert console_server.pair_link("100.1.2.3", port, TOKEN) == f"cyraen://pair?host=100.1.2.3&port={port}&key={TOKEN}"


def test_pair_page_rejects_remote_clients(tmp_path):
    """LAN/Tailscale'den gelen istemci token iceren eslestirme sayfasini goremez (403)."""
    from web.console_server import _lan_ip

    lan = _lan_ip()
    if lan.startswith("127."):
        pytest.skip("ag arayuzu yok")
    port = _free_port()
    srv = ConsoleServer(outbox_path=tmp_path / "o", inbox_path=tmp_path / "i", port=port, bind="0.0.0.0", token=TOKEN)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for _ in range(50):
            try:
                socket.create_connection((lan, port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://{lan}:{port}/pair", timeout=5)
        assert exc.value.code == 403
    finally:
        srv.stop()


# ------------------------------------------------------------ arac gruplari
def test_disabled_groups_are_hidden_and_not_run():
    from google.genai import types as gtypes
    from tools.tool_declarations import build_declarations
    from tools.tool_runner import ToolRunner

    names = {d.name for d in build_declarations({"adb"})}
    assert "adb_shell" not in names and "show_map" in names and "get_current_datetime" in names
    runner = ToolRunner(disabled_groups={"adb"})
    resp = asyncio_run(runner.dispatch(gtypes.FunctionCall(name="adb_shell", args={"command": "ls"})))
    assert "Bilinmeyen arac" in resp.response["error"]


def test_adb_open_redirects_when_phone_app_connected():
    from google.genai import types as gtypes
    from tools.tool_runner import ToolRunner
    from web.phone_link import PHONE

    runner = ToolRunner()
    PHONE.attach()
    try:
        resp = asyncio_run(runner.dispatch(gtypes.FunctionCall(name="adb_open", args={"target": "x"})))
        assert "open_phone_app" in resp.response["error"]
    finally:
        PHONE.detach()


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# ------------------------------------------------------------ token yenileme
def test_rotate_token_replaces_only_its_line(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("rotate_token", Path(__file__).parent.parent / "scripts" / "rotate_token.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = tmp_path / ".env"
    env.write_bytes(b"A=1\r\nCYRAEN_WEB_TOKEN=eski\r\nB=2\r\n")
    assert mod.main(["--env", str(env)]) == 0
    text = env.read_bytes().decode()
    new = text.split("CYRAEN_WEB_TOKEN=")[1].split("\r\n")[0]
    assert text.startswith("A=1\r\n") and text.endswith("B=2\r\n") and new != "eski" and len(new) >= 20
    assert new not in capsys.readouterr().out  # yeni deger ekrana yazilmaz
    env2 = tmp_path / "bos.env"
    mod.rotate(env2)
    assert env2.read_text().startswith("CYRAEN_WEB_TOKEN=")
