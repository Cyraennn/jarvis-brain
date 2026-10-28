"""Web konsolu: kimlik dogrulama, CORS allowlist, loopback varsayilani."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from web.console_server import ConsoleServer


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    port = _free_port()
    srv = ConsoleServer(
        outbox_path=tmp_path / "outbox.txt",
        inbox_path=tmp_path / "inbox.txt",
        port=port,
        bind="127.0.0.1",
        token="s3cret-token",
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield srv, port
    srv.stop()


def _req(port, path, *, headers=None, data=None):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_rejects_missing_or_wrong_token(server):
    _, port = server
    assert _req(port, "/api/state")[0] in (401, 403)
    assert _req(port, "/api/state?key=wrong")[0] in (401, 403)


def test_accepts_query_and_header_token(server):
    _, port = server
    assert _req(port, "/api/state?key=s3cret-token")[0] == 200
    assert _req(port, "/api/state", headers={"X-Jarvis-Key": "s3cret-token"})[0] == 200


def test_cors_is_allowlisted_not_wildcard(server):
    _, port = server
    _, h, _ = _req(port, "/api/state?key=s3cret-token", headers={"Origin": "http://evil.example"})
    assert "Access-Control-Allow-Origin" not in h
    _, h, _ = _req(port, "/api/state?key=s3cret-token", headers={"Origin": "http://localhost:8000"})
    assert h.get("Access-Control-Allow-Origin") == "http://localhost:8000"


def test_no_token_forces_loopback_bind(tmp_path):
    srv = ConsoleServer(outbox_path=tmp_path / "o", inbox_path=tmp_path / "i", port=1, bind="0.0.0.0", token="")
    assert srv.bind == "127.0.0.1"


def test_control_wake_toggle_reaches_callback_and_bus(server):
    from web.event_bus import BUS

    srv, port = server
    seen = []
    srv._on_control = lambda action: seen.append(action) or {"wake": action == "wake_on"}
    hdr = {"X-Jarvis-Key": "s3cret-token", "Content-Type": "application/json"}
    for action, expected in (("wake_on", True), ("wake_off", False)):
        status, _, body = _req(port, "/api/control", headers=hdr,
                               data=json.dumps({"action": action}).encode())
        assert status == 200 and json.loads(body)["wake"] is expected
        assert BUS.snapshot()["wake"] is expected
    assert seen == ["wake_on", "wake_off"]
    status, _, _ = _req(port, "/api/control", headers=hdr, data=b'{"action": "wake_maybe"}')
    assert status == 400
