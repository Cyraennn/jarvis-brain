"""Decision Pipeline panosu: FastAPI uclari, canli yayin (BUS -> /ws/decisions), maliyet tahmini."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from router.events import BUS, DecisionBus
from router.log import RoutingLog
from router.registry import ModelRegistry
from ui.dashboard.server import create_app, read_decisions


@pytest.fixture
def app_client(tmp_path):
    log = tmp_path / "routing.jsonl"
    rows = [{"kind": "decision", "request_id": f"r{i}", "task_type": "kod"} for i in range(5)]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nbozuk satir\n", encoding="utf-8")
    settings = get_settings().model_copy(update={"routing_log_path": log})
    with TestClient(create_app(settings)) as client:
        yield client


def test_page_and_assets_are_served(app_client):
    page = app_client.get("/dashboard/")
    assert page.status_code == 200 and "DECISION PIPELINE" in page.text
    assert app_client.get("/dashboard/app.js").headers["content-type"].startswith("text/javascript")
    assert app_client.get("/dashboard/style.css").status_code == 200


def test_only_whitelisted_files_are_served(app_client):
    assert app_client.get("/dashboard/server.py").status_code == 404
    assert app_client.get("/dashboard/..%2F..%2Fconfig%2Fsettings.py").status_code == 404


def test_decisions_endpoint_tails_log_and_skips_bad_lines(app_client):
    rows = app_client.get("/api/decisions?limit=3").json()["rows"]
    assert [r["request_id"] for r in rows] == ["r3", "r4"]   # son 3 satir: r3, r4, bozuk
    assert len(app_client.get("/api/decisions").json()["rows"]) == 5


def test_read_decisions_missing_file(tmp_path):
    assert read_decisions(tmp_path / "yok.jsonl") == []


def test_info_lists_models_prices_and_thresholds(app_client):
    info = app_client.get("/api/info").json()
    ids = {m["id"] for m in info["models"]}
    assert "claude-opus-5-5" in ids and info["thresholds"]["task"] == 0.75
    claude = next(m for m in info["models"] if m["id"] == "claude-opus-5-5")
    assert claude["price"] == {"input": 4.0, "output": 20.0}


def test_websocket_receives_events_published_from_another_thread(app_client):
    with app_client.websocket_connect("/ws/decisions") as ws:
        assert ws.receive_json()["kind"] == "hello"
        for _ in range(50):   # abonelik sunucu tarafinda kurulana kadar
            if BUS.subscriber_count:
                break
            threading.Event().wait(0.02)
        thread = threading.Thread(target=BUS.publish, args=({"kind": "decision", "request_id": "canli"},))
        thread.start()
        thread.join()
        assert ws.receive_json()["request_id"] == "canli"


def test_routing_log_publishes_rows_to_bus(tmp_path):
    bus_events = []

    async def scenario():
        queue = BUS.subscribe()
        try:
            RoutingLog(tmp_path / "r.jsonl").write("decision", {"request_id": "x"})
            bus_events.append(await asyncio.wait_for(queue.get(), 1))
        finally:
            BUS.unsubscribe(queue)

    asyncio.run(scenario())
    assert bus_events[0]["kind"] == "decision" and bus_events[0]["request_id"] == "x"
    assert json.loads((tmp_path / "r.jsonl").read_text("utf-8"))["request_id"] == "x"


def test_slow_subscriber_drops_oldest_instead_of_blocking():
    bus = DecisionBus()

    async def scenario():
        queue = bus.subscribe()
        for i in range(600):
            bus.publish({"i": i})
        await asyncio.sleep(0.05)
        return queue

    queue = asyncio.run(scenario())
    assert queue.qsize() == 500 and queue.get_nowait()["i"] == 100


def test_cost_estimate_only_for_priced_models():
    reg = ModelRegistry.load(get_settings().router_config_path)
    assert reg.estimate_cost("gemini-flash-lite-latest", request_chars=4000) == 0.0
    one = reg.estimate_cost("claude-opus-5-5", request_chars=4000, calls=1)
    # (4000/4 + 1500) * 4$/1M + 600 * 20$/1M = 0.01 + 0.012
    assert one == pytest.approx(0.022)
    assert reg.estimate_cost("claude-opus-5-5", request_chars=4000, calls=3) == pytest.approx(3 * one)
