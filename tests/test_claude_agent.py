"""Claude yolu: arac dongusu + basarisizlikta OpenRouter'a ACIK gecis."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agents.agent import Agent, is_claude_model, is_openrouter_model
from agents.schemas import AgentSpec


def _text(t: str):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name: str, args: dict):
    return SimpleNamespace(type="tool_use", id="tu1", name=name, input=args)


class FakeClaude:
    available = True

    def __init__(self, replies: list) -> None:
        self.replies = replies
        self.calls: list[dict] = []

    async def create(self, messages, *, model, system="", tools=None, effort=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "model": model, "tools": tools,
                           "effort": effort})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeRouter:
    available = True

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, model, fallback_models=None, info=None, **kw):  # noqa: ANN001
        self.calls += 1
        info.update(model=model, fallback=False)
        return SimpleNamespace(content="openrouter cevabi", tool_calls=None)


def _agent(claude, router=None) -> Agent:
    spec = AgentSpec(name="kodcu", title="K", description="d", model="claude-opus-5-5",
                     fallback_model="qwen/qwen3.8-27b:free", effort="high")
    return Agent(spec, None, default_models=["gemini-x"], default_max_steps=3,
                 openrouter=router or FakeRouter(), claude=claude)


def test_model_kinds():
    assert is_claude_model("claude-opus-5-5") and not is_openrouter_model("claude-opus-5-5")
    assert not is_claude_model("anthropic/claude-sonnet-5.5")
    agent = _agent(FakeClaude([]))
    assert agent.claude_models == ["claude-opus-5-5"]
    assert agent.openrouter_models == ["qwen/qwen3.8-27b:free"]
    assert agent.models == ["gemini-x"]  # Claude modeli Gemini zincirine karismaz


def test_claude_tool_loop():
    def read_file(path: str) -> dict:
        """Dosya okur."""
        return {"path": path, "content": "print(1)"}

    claude = FakeClaude([
        SimpleNamespace(stop_reason="tool_use", model="claude-opus-5-5",
                        content=[_tool_use("read_file", {"path": "a.py"})]),
        SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                        content=[_text("a.py 1 yazdiriyor.")]),
    ])
    router = FakeRouter()
    agent = _agent(claude, router)
    agent._callables = [read_file]
    agent._by_name = {"read_file": read_file}

    result = asyncio.run(agent.run("a.py ne yapiyor"))
    assert result.ok and result.text == "a.py 1 yazdiriyor."
    assert result.tool_calls == ["read_file"] and result.model == "claude-opus-5-5"
    assert not result.fallback and router.calls == 0
    first = claude.calls[0]
    assert first["effort"] == "high"
    assert first["tools"][0]["name"] == "read_file" and "input_schema" in first["tools"][0]
    tool_result = claude.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu1"
    assert json.loads(tool_result["content"])["path"] == "a.py"


def test_claude_error_falls_back_to_openrouter():
    router = FakeRouter()
    agent = _agent(FakeClaude([RuntimeError("401 invalid x-api-key")]), router)
    result = asyncio.run(agent.run("kod yaz"))
    assert result.ok and result.text == "openrouter cevabi" and router.calls == 1
    assert result.fallback and result.primary_model == "claude-opus-5-5"


def test_claude_refusal_falls_back_to_openrouter():
    router = FakeRouter()
    agent = _agent(FakeClaude([SimpleNamespace(stop_reason="refusal", model="claude-opus-5-5",
                                               content=[])]), router)
    result = asyncio.run(agent.run("kod yaz"))
    assert result.text == "openrouter cevabi" and result.fallback


def test_no_claude_key_falls_back():
    claude = FakeClaude([])
    claude.available = False
    router = FakeRouter()
    result = asyncio.run(_agent(claude, router).run("kod yaz"))
    assert result.text == "openrouter cevabi" and router.calls == 1 and claude.calls == []
