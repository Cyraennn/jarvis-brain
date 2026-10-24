"""MCP istemcisi - gercek stdio test sunucusuna (tests/fixtures/echo_mcp_server.py) baglanir."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from google.genai import types

from agents.agent_tools import build_callables
from core.async_worker import get_worker
from tools import mcp_hub
from tools.tool_declarations import build_declarations
from tools.tool_runner import ToolRunner

SERVER = Path(__file__).parent / "fixtures" / "echo_mcp_server.py"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "echo": {"command": sys.executable, "args": [str(SERVER)], "confirm": "write"},
        "kapali": {"command": "yok", "disabled": True},
    }}), encoding="utf-8")
    h = mcp_hub.MCPHub(cfg)
    monkeypatch.setattr(mcp_hub, "_hub", h)
    yield h
    get_worker().shutdown()


def test_expand_env(monkeypatch):
    monkeypatch.setenv("CYRAEN_TEST_TOKEN", "abc")
    spec = mcp_hub.ServerSpec.from_dict("x", {"command": "c", "env": {"T": "${CYRAEN_TEST_TOKEN}"}})
    assert spec.env == {"T": "abc"}


def test_name_based_confirm(hub):
    assert hub.needs_confirm("echo", "delete_item")
    assert hub.needs_confirm("echo", "createIssue")
    assert not hub.needs_confirm("echo", "echo")
    assert not hub.needs_confirm("echo", "get_settings")


def test_servers_list_and_errors(hub):
    names = {s["name"] for s in hub.servers()["servers"]}
    assert names == {"echo", "kapali"}
    assert "error" in hub.list_tools("yok")
    assert "devre disi" in hub.list_tools("kapali")["error"]
    assert "JSON" in hub.call("echo", "echo", "{bozuk")["error"]


def test_list_and_call(hub):
    listed = hub.list_tools("echo")
    names = {t["name"] for t in listed["tools"]}
    assert {"echo", "big_text", "delete_item"} <= names
    assert "zorunlu" in next(t for t in listed["tools"] if t["name"] == "echo")["params"]["text"]
    assert hub.list_tools("echo", query="sil")["total"] == 1

    assert hub.call("echo", "echo", '{"text": "merhaba"}') == {"result": "echo: merhaba"}
    big = hub.call("echo", "big_text", '{"n": 9000}')["result"]
    assert big.endswith("[kirpildi]") and len(big) < 6100
    assert hub.servers()["servers"][0]["status"] == "bagli"


def test_agent_cannot_run_confirm_tools(hub):
    assert "onay" in mcp_hub.mcp_call_readonly("echo", "delete_item", '{"item_id": "1"}')["error"]
    assert mcp_hub.mcp_call_readonly("echo", "echo", '{"text": "a"}') == {"result": "echo: a"}


def test_runner_confirm_gate(hub):
    prompts: list[str] = []
    runner = ToolRunner(confirm=lambda p: prompts.append(p) or False)
    call = types.FunctionCall(id="1", name="mcp_call",
                              args={"server": "echo", "tool": "delete_item", "arguments_json": '{"item_id": "7"}'})
    resp = asyncio.run(runner.dispatch(call))
    assert resp.response["status"] == "iptal edildi" and "delete_item" in prompts[0]

    runner = ToolRunner(confirm=lambda p: True)
    resp = asyncio.run(runner.dispatch(call))
    assert resp.response == {"result": "silindi: 7"}


def test_registered_everywhere():
    decl = {d.name for d in build_declarations()}
    assert {"mcp_servers", "mcp_list_tools", "mcp_call", "browser_task", "browser_open"} <= decl
    runner = ToolRunner()
    assert decl <= set(runner.tool_names)
    caps = {fn.__name__ for fn in build_callables(["mcp", "browser"])}
    assert {"mcp_servers", "mcp_list_tools", "mcp_call", "browser_open", "browser_snapshot",
            "browser_click", "browser_type"} <= caps
