"""Uzaktan onay akisi: ConfirmRegistry + POST /api/confirm + WebEngineObserver.confirm()."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from web.confirm_registry import REGISTRY
from web.console_server import ConsoleServer
from web.web_observer import WebEngineObserver, WebOrchestratorObserver


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


def _post(port, path, body):
    data = json.dumps(body).encode("utf-8")
    r = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}?key=s3cret-token",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_confirm_endpoint_resolves_pending(server):
    _, port = server
    pc = REGISTRY.create("Dosyayi sil?", source="engine")
    try:
        status, payload = _post(port, "/api/confirm", {"id": pc.id, "approve": True})
        assert status == 200
        assert payload["approved"] is True
        assert pc.wait(1.0) is True
        assert pc.result is True
    finally:
        REGISTRY.discard(pc.id)


def test_confirm_endpoint_unknown_id_is_404(server):
    _, port = server
    status, payload = _post(port, "/api/confirm", {"id": "does-not-exist", "approve": True})
    assert status == 404


def test_confirm_endpoint_requires_token(server):
    _, port = server
    pc = REGISTRY.create("token'siz istek", source="engine")
    try:
        data = json.dumps({"id": pc.id, "approve": True}).encode("utf-8")
        r = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/confirm",  # key yok
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(r, timeout=3)
        assert exc.value.code == 401
        # cozulmedi - hala bekliyor
        assert pc.wait(0.2) is False
    finally:
        REGISTRY.discard(pc.id)


def test_web_engine_observer_confirm_round_trip():
    observer = WebEngineObserver(confirm_timeout=5.0)
    result = {}

    def _run():
        result["approved"] = observer.confirm("Uygulamayi kapat?")

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    pending = None
    for _ in range(50):
        pending = next(
            (p for p in REGISTRY.pending_list() if p["prompt"] == "Uygulamayi kapat?"), None
        )
        if pending is not None:
            break
        time.sleep(0.05)
    assert pending is not None, "onay istegi registry'de gorunmedi"

    REGISTRY.resolve(pending["id"], True)
    t.join(timeout=2.0)
    assert result.get("approved") is True


def test_web_engine_observer_confirm_times_out_and_denies():
    observer = WebEngineObserver(confirm_timeout=0.2)
    assert observer.confirm("kimse cevap vermeyecek") is False


def test_web_orchestrator_observer_confirm_round_trip():
    observer = WebOrchestratorObserver(confirm_timeout=5.0)
    result = {}

    def _run():
        result["approved"] = observer.confirm("Ajan gorevi calistirilsin mi?")

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    pending = None
    for _ in range(50):
        pending = next(
            (p for p in REGISTRY.pending_list() if p["prompt"] == "Ajan gorevi calistirilsin mi?"),
            None,
        )
        if pending is not None:
            break
        time.sleep(0.05)
    assert pending is not None
    assert pending["source"] == "orchestrator"

    REGISTRY.resolve(pending["id"], False)
    t.join(timeout=2.0)
    assert result.get("approved") is False
