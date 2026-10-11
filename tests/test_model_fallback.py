"""Yedek modele gecis ASLA sessiz olmamali: log + kanca + cevapta isaret."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents import genai_util
from agents.genai_util import fallback_note, generate_with_retry


class FakeModels:
    def __init__(self, behaviour: dict[str, object]) -> None:
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def generate_content(self, *, model, contents, config):  # noqa: ANN001
        self.calls.append(model)
        outcome = self.behaviour[model]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


def _client(behaviour: dict[str, object]):
    models = FakeModels(behaviour)
    return SimpleNamespace(aio=SimpleNamespace(models=models)), models


def test_primary_ok_no_fallback_flag():
    client, models = _client({"a": "ok"})
    info: dict = {}
    resp = asyncio.run(generate_with_retry(client, model=["a", "b"], contents="x", info=info))
    assert resp.text == "ok" and models.calls == ["a"]
    assert info == {"model": "a", "primary": "a", "fallback": False}
    assert fallback_note(info) == ""


def test_fallback_is_announced_and_marked(monkeypatch):
    hooks = []
    monkeypatch.setattr(genai_util, "FALLBACK_HOOKS", [hooks.append])
    client, models = _client({
        "a": RuntimeError("404 NOT_FOUND model not found"),
        "b": "yedek cevap",
    })
    info: dict = {}
    resp = asyncio.run(generate_with_retry(client, model=["a", "b"], contents="x", info=info))
    assert resp.text == "yedek cevap" and models.calls == ["a", "b"]
    assert info["fallback"] is True and info["model"] == "b" and info["fallback_from"] == ["a"]
    assert hooks and hooks[0]["from"] == "a" and hooks[0]["to"] == "b"
    assert "YEDEK MODEL: b" in fallback_note(info) and "a" in fallback_note(info)


def test_last_model_failure_raises():
    client, _ = _client({"a": RuntimeError("404 NOT_FOUND gone")})
    with pytest.raises(RuntimeError):
        asyncio.run(generate_with_retry(client, model=["a"], contents="x"))


def test_agent_result_carries_fallback(monkeypatch):
    from agents.agent import Agent
    from agents.schemas import AgentSpec

    async def fake_generate(client, *, model, contents, config, info=None, **kw):  # noqa: ANN001
        info.update({"model": "yedek-model", "primary": "asil-model", "fallback": True})
        return SimpleNamespace(text="cevap", candidates=[None])

    monkeypatch.setattr("agents.agent.generate_with_retry", fake_generate)
    spec = AgentSpec(name="t", title="T", description="d")
    agent = Agent(spec, client=SimpleNamespace(), default_models=["asil-model", "yedek-model"],
                  default_max_steps=2)
    monkeypatch.setattr(agent, "_build_config", lambda: None)
    result = asyncio.run(agent.run("gorev"))
    assert result.ok and result.fallback and result.model == "yedek-model"
    assert result.primary_model == "asil-model"
