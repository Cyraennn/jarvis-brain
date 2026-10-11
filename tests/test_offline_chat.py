"""Cevrimdisi yazili sohbet + cevrimdisiyken bulutu atlama."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import types

from agents import genai_util
from agents.genai_util import generate_with_retry
from core import offline_chat
from core.local_llm import LocalLLM
from core.offline_chat import OfflineChat, offline_declarations


class ScriptedOllama:
    """Sirayla verilen mesajlari donduren Ollama taklidi; gelen govdeleri saklar."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        self.bodies.append(json.loads(request.content))
        if not self.replies:
            return httpx.Response(500, text="bitti")
        return httpx.Response(200, json={"model": "qwen2.5:7b", "message": self.replies.pop(0)})

    def client(self) -> LocalLLM:
        return LocalLLM(models=["qwen2.5:7b"], transport=httpx.MockTransport(self))


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def dispatch(self, call: types.FunctionCall) -> types.FunctionResponse:
        self.calls.append((call.name, dict(call.args or {})))
        return types.FunctionResponse(name=call.name, response={"saat": "21:05"})


def _tool_call(name: str, **args) -> dict:
    return {"content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def _chat(replies: list[dict], events: list | None = None):
    fake = ScriptedOllama(replies)
    runner = FakeRunner()
    notify = (lambda *a: events.append(a)) if events is not None else (lambda *a: None)
    return OfflineChat(runner, fake.client(), notify=notify), fake, runner


# ------------------------------------------------------------------ sohbet
def test_tool_turn_then_answer():
    events: list = []
    chat, fake, runner = _chat(
        [_tool_call("get_current_datetime"), {"content": "Saat 21:05, efendim."}], events
    )
    answer = asyncio.run(chat.reply("Saat kac?"))
    assert answer == "Saat 21:05, efendim."
    assert runner.calls == [("get_current_datetime", {})]
    assert ("on_tool_call", ["get_current_datetime"]) in events
    assert ("on_assistant_transcript", "(yerel) Saat 21:05, efendim.", True) in events
    # ikinci istekte arac sonucu modele "tool" mesaji olarak gitti
    assert fake.bodies[1]["messages"][-1]["role"] == "tool"
    assert "21:05" in fake.bodies[1]["messages"][-1]["content"]


def test_only_offline_tools_sent():
    chat, fake, _ = _chat([{"content": "tamam"}])
    asyncio.run(chat.reply("selam"))
    names = {t["function"]["name"] for t in fake.bodies[0]["tools"]}
    assert names == set(offline_chat.OFFLINE_TOOLS)
    assert "web_search" not in names and "send_email" not in names


def test_unknown_tool_is_refused_without_dispatch():
    chat, _, runner = _chat([_tool_call("send_email", to="x"), {"content": "Yapamam."}])
    assert asyncio.run(chat.reply("mail at")) == "Yapamam."
    assert runner.calls == []


def test_step_limit_message():
    chat, _, _ = _chat([_tool_call("get_current_datetime")] * offline_chat.MAX_STEPS)
    assert "adim siniri" in asyncio.run(chat.reply("dongu"))


def test_history_kept_and_trimmed(monkeypatch):
    monkeypatch.setattr(offline_chat, "MAX_TURNS", 2)
    chat, fake, _ = _chat([{"content": f"yanit {i}"} for i in range(4)])
    for i in range(4):
        asyncio.run(chat.reply(f"soru {i}"))
    sent = [m["content"] for m in fake.bodies[-1]["messages"] if m["role"] == "user"]
    assert sent == ["soru 1", "soru 2", "soru 3"]  # gecmiste 2 eski tur + yeni soru
    user_turns = [c for c in chat.history if c.role == "user"]
    assert len(user_turns) == 2


def test_local_down_message():
    chat, _, _ = _chat([])
    assert "Ollama" in asyncio.run(chat.reply("selam"))


def test_declarations_exist_for_all_offline_tools():
    assert {fd.name for fd in offline_declarations()} == set(offline_chat.OFFLINE_TOOLS)


# ------------------------------------------------------------------ cevrimdisi bulut atlama
def _offline(monkeypatch, local):
    async def offline() -> bool:
        return False
    monkeypatch.setattr(genai_util, "_is_online", offline)
    monkeypatch.setattr(genai_util, "_get_local", lambda: local)


def _gemini_spy():
    calls: list[str] = []

    async def generate_content(*, model, contents, config):  # noqa: ANN001
        calls.append(model)
        raise AssertionError("cevrimdisiyken bulut denenmemeli")
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content)))
    return client, calls


def test_offline_skips_cloud_entirely(monkeypatch):
    fake = ScriptedOllama([{"content": "yerel"}])
    _offline(monkeypatch, fake.client())
    client, calls = _gemini_spy()
    info: dict = {}
    resp = asyncio.run(generate_with_retry(client, model=["g1", "g2"], contents="x", info=info))
    assert resp.text == "yerel" and calls == []
    assert info["fallback"] is True and info["model"] == "ollama/qwen2.5:7b"


def test_offline_and_local_fails_raises_connection_error(monkeypatch):
    _offline(monkeypatch, ScriptedOllama([]).client())
    client, calls = _gemini_spy()
    with pytest.raises(ConnectionError):
        asyncio.run(generate_with_retry(client, model=["g1"], contents="x"))
    assert calls == []


def test_no_local_means_no_probe(monkeypatch):
    async def boom() -> bool:
        raise AssertionError("yerel model yokken yoklama yapilmamali")
    monkeypatch.setattr(genai_util, "_is_online", boom)
    monkeypatch.setattr(genai_util, "_get_local", lambda: None)

    async def ok(*, model, contents, config):  # noqa: ANN001
        return SimpleNamespace(text="bulut")
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=ok)))
    assert asyncio.run(generate_with_retry(client, model="g1", contents="x")).text == "bulut"


# ------------------------------------------------------------------ motor yonlendirmesi
def _engine(tmp_path, session, chat):
    from core.brain_engine import BrainEngine

    engine = BrainEngine.__new__(BrainEngine)
    engine.session = session
    engine._offline_chat = chat
    engine.settings = SimpleNamespace(bridge_outbox_path=tmp_path / "outbox.txt")
    engine._notify = lambda *a: None
    return engine


def test_inject_without_session_goes_to_local_chat(tmp_path):
    replies: list[str] = []

    class Chat:
        async def reply(self, text: str) -> str:
            replies.append(text)
            return "ok"

    engine = _engine(tmp_path, None, Chat())

    async def run() -> None:
        engine.inject_bridge_message("saat kac")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    asyncio.run(run())
    assert replies == ["saat kac"]
    assert not (tmp_path / "outbox.txt").exists()


def test_inject_with_session_writes_outbox(tmp_path):
    engine = _engine(tmp_path, object(), None)
    engine.inject_bridge_message("merhaba")
    assert (tmp_path / "outbox.txt").read_text(encoding="utf-8") == "merhaba\n"


def test_warm_up_loads_main_model():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append({"path": request.url.path, **json.loads(request.content)})
        return httpx.Response(200, json={"done": True})

    local = LocalLLM(models=["qwen2.5:7b", "qwen2.5:1.5b"], transport=httpx.MockTransport(handler))
    assert asyncio.run(local.warm_up()) is True
    assert bodies == [{"path": "/api/generate", "model": "qwen2.5:7b", "keep_alive": "10m",
                       "options": {"num_ctx": 8192}}]
