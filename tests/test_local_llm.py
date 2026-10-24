"""Yerel model yedegi (Ollama): istek/yanit cevirisi + bulut zinciri bitince devralma."""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import httpx
import pytest
from google.genai import types

from agents import genai_util
from agents.genai_util import fallback_note, generate_with_retry
from core import local_llm
from core.local_llm import LocalLLM, from_ollama, supports, to_ollama


def okul_status(days: int = 7, course: str | None = None) -> dict:
    """Yaklasan sinav ve odevleri verir."""
    return {}


def _tool_config(**kw) -> types.GenerateContentConfig:
    fd = types.FunctionDeclaration.from_callable_with_api_option(
        callable=okul_status, api_option="GEMINI_API"
    )
    return types.GenerateContentConfig(
        system_instruction="Sen CYRAEN'sin.", tools=[types.Tool(function_declarations=[fd])], **kw
    )


class FakeOllama:
    """httpx.MockTransport arkasinda Ollama taklidi; modele gore yanit/HTTP durum."""

    def __init__(self, replies: dict[str, object], up: bool = True) -> None:
        self.replies = replies
        self.up = up
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("kapali", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        body = json.loads(request.content)
        self.bodies.append(body)
        reply = self.replies.get(body["model"], 404)
        if isinstance(reply, int):
            return httpx.Response(reply, text="model not found")
        return httpx.Response(200, json={"model": body["model"], "message": reply})

    def client(self, models=("qwen2.5:7b", "qwen2.5:1.5b")) -> LocalLLM:
        return LocalLLM(models=list(models), transport=httpx.MockTransport(self))


# ------------------------------------------------------------------ ceviri
def test_text_request_round_trip():
    body = to_ollama("Merhaba", types.GenerateContentConfig(
        system_instruction="sistem", temperature=0.3, response_mime_type="application/json"
    ))
    assert body["messages"] == [
        {"role": "system", "content": "sistem"}, {"role": "user", "content": "Merhaba"},
    ]
    assert body["options"] == {"temperature": 0.3} and body["format"] == "json"
    resp = from_ollama({"model": "qwen2.5:7b", "message": {"content": " Selam efendim "}})
    assert resp.text == "Selam efendim"


def test_tool_schema_and_tool_turns():
    contents = [
        types.Content(role="user", parts=[types.Part(text="Sinavim var mi?")]),
        types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name="okul_status", args={"days": 3})
        )]),
        types.Content(role="user", parts=[types.Part.from_function_response(
            name="okul_status", response={"result": {"sinav": "Fizik"}}
        )]),
    ]
    body = to_ollama(contents, _tool_config())
    fn = body["tools"][0]["function"]
    assert fn["name"] == "okul_status"
    assert fn["parameters"]["type"] == "object"
    assert fn["parameters"]["properties"]["days"]["type"] == "integer"
    assert "nullable" not in fn["parameters"]["properties"]["course"]
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert body["messages"][2]["tool_calls"][0]["function"] == {
        "name": "okul_status", "arguments": {"days": 3}
    }
    assert body["messages"][3]["tool_name"] == "okul_status"
    assert "Fizik" in body["messages"][3]["content"]


def test_tool_call_response_becomes_function_call_part():
    resp = from_ollama({"message": {"content": "", "tool_calls": [
        {"function": {"name": "okul_status", "arguments": {"days": 2}}},
        {"function": {"name": "okul_status", "arguments": '{"days": 5}'}},
    ]}})
    calls = [p.function_call for p in resp.candidates[0].content.parts]
    assert [c.name for c in calls] == ["okul_status", "okul_status"]
    assert calls[0].args == {"days": 2} and calls[1].args == {"days": 5}


def test_media_request_not_supported():
    part = types.Part.from_bytes(data=b"\x00\x01", mime_type="audio/ogg")
    assert not supports([types.Content(role="user", parts=[part])])
    assert supports("duz metin") and supports(["a", types.Part(text="b")])


def test_google_search_dropped_with_note():
    cfg = types.GenerateContentConfig(
        system_instruction="sys", tools=[types.Tool(google_search=types.GoogleSearch())]
    )
    body = to_ollama("Mac kac kac bitti?", cfg)
    assert "tools" not in body
    assert "web aramasi YOK" in body["messages"][0]["content"]


# ------------------------------------------------------------------ istemci
def test_big_model_missing_falls_to_small():
    fake = FakeOllama({"qwen2.5:1.5b": {"content": "kucuk model"}})
    resp, used = asyncio.run(fake.client().generate("selam"))
    assert used == "qwen2.5:1.5b" and resp.text == "kucuk model"
    assert [b["model"] for b in fake.bodies] == ["qwen2.5:7b", "qwen2.5:1.5b"]
    assert fake.bodies[0]["options"]["num_ctx"] == 8192 and fake.bodies[0]["stream"] is False


def test_all_local_models_fail_raises():
    fake = FakeOllama({})
    with pytest.raises(local_llm.LocalLLMError):
        asyncio.run(fake.client().generate("selam"))


# ------------------------------------------------------------------ generate_with_retry
def _gemini(error: Exception):
    async def generate_content(*, model, contents, config):  # noqa: ANN001
        raise error
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content
    )))


@pytest.mark.parametrize("error", [
    RuntimeError("429 RESOURCE_EXHAUSTED quota PerDay exceeded"),
    RuntimeError("404 NOT_FOUND model not found"),
])
def test_cloud_exhausted_hands_over_to_local(monkeypatch, error):
    hooks = []
    fake = FakeOllama({"qwen2.5:7b": {"content": "yerelden cevap"}})
    monkeypatch.setattr(genai_util, "_get_local", fake.client)
    monkeypatch.setattr(genai_util, "FALLBACK_HOOKS", [hooks.append])
    info: dict = {}
    resp = asyncio.run(generate_with_retry(
        _gemini(error), model=["gemini-a"], contents="selam", info=info
    ))
    assert resp.text == "yerelden cevap"
    assert info["fallback"] is True and info["model"] == "ollama/qwen2.5:7b"
    assert info["primary"] == "gemini-a" and info["fallback_from"] == ["gemini-a"]
    assert hooks and hooks[0]["to"] == "ollama/qwen2.5:7b"
    assert "YEDEK MODEL: ollama/qwen2.5:7b" in fallback_note(info)


def test_local_down_or_disabled_keeps_original_error(monkeypatch):
    err = RuntimeError("404 NOT_FOUND model not found")
    monkeypatch.setattr(genai_util, "_get_local", FakeOllama({}, up=False).client)
    with pytest.raises(RuntimeError, match="NOT_FOUND"):
        asyncio.run(generate_with_retry(_gemini(err), model=["gemini-a"], contents="x"))
    monkeypatch.setattr(genai_util, "_get_local", lambda: None)
    with pytest.raises(RuntimeError, match="NOT_FOUND"):
        asyncio.run(generate_with_retry(_gemini(err), model=["gemini-a"], contents="x"))


def test_local_failure_recorded_and_original_raised(monkeypatch):
    monkeypatch.setattr(genai_util, "_get_local", FakeOllama({}).client)
    info: dict = {}
    with pytest.raises(RuntimeError, match="NOT_FOUND"):
        asyncio.run(generate_with_retry(
            _gemini(RuntimeError("404 NOT_FOUND gone")), model=["gemini-a"], contents="x",
            info=info,
        ))
    assert "Yerel model yanit vermedi" in info["local_error"]


def test_media_request_never_reaches_local(monkeypatch):
    fake = FakeOllama({"qwen2.5:7b": {"content": "olmamali"}})
    monkeypatch.setattr(genai_util, "_get_local", fake.client)
    part = types.Part.from_bytes(data=b"\x00", mime_type="image/png")
    with pytest.raises(RuntimeError):
        asyncio.run(generate_with_retry(
            _gemini(RuntimeError("404 NOT_FOUND gone")), model=["gemini-a"],
            contents=[types.Content(role="user", parts=[part])],
        ))
    assert fake.bodies == []


def test_server_disables_local_by_default(monkeypatch):
    from config.settings import Settings
    from server.config import server_settings

    monkeypatch.delenv("CYRAEN_LOCAL_LLM", raising=False)
    cfg = SimpleNamespace(bind="127.0.0.1", token="x" * 24)
    assert server_settings(Settings(gemini_api_key="x"), cfg).local_llm_enabled is False
    assert local_llm._build(server_settings(Settings(gemini_api_key="x"), cfg)) is None


# ------------------------------------------------------------------ canli
@pytest.mark.skipif(os.environ.get("CYRAEN_LIVE_TESTS") != "1",
                    reason="canli test: CYRAEN_LIVE_TESTS=1 ve calisan Ollama gerekir")
def test_live_ollama_tool_turn():
    client = LocalLLM(models=["qwen2.5:7b"])
    assert asyncio.run(client.is_up())
    resp, _ = asyncio.run(client.generate(
        "Onumuzdeki 3 gun icin okul durumumu kontrol et.", _tool_config()
    ))
    calls = [p.function_call for p in resp.candidates[0].content.parts if p.function_call]
    assert calls and calls[0].name == "okul_status"
    resp, _ = asyncio.run(client.generate(
        "Turkiye'nin baskenti neresi? Tek kelime.", types.GenerateContentConfig(temperature=0)
    ))
    assert "Ankara" in resp.text
