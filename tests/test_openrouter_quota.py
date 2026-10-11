"""OpenRouter: paylasimli ucretsiz gunluk kota dolunca :free modeller atlanir."""
import asyncio
from types import SimpleNamespace

import pytest

from core import openrouter_client as orc

QUOTA_429 = RuntimeError("Error code: 429 - {'error': {'message': 'Rate limit exceeded: "
                         "free-models-per-day. Add 10 credits to unlock 1000 free model requests'}}")


@pytest.fixture(autouse=True)
def _reset_quota(monkeypatch):
    monkeypatch.setattr(orc, "_free_quota_until", 0.0)


def _client(behaviour):
    calls = []

    async def create(model, **kw):
        calls.append(model)
        out = behaviour(model)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(model=model, choices=[SimpleNamespace(message=SimpleNamespace(
            content=out, tool_calls=None))])

    c = orc.OpenRouterClient(api_key="k")
    c.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return c, calls


def test_daily_quota_skips_remaining_free_models_and_later_calls():
    c, calls = _client(lambda m: QUOTA_429)
    with pytest.raises(orc.OpenRouterQuotaError):
        asyncio.run(c.chat([], model="a/x:free", fallback_models=["b/y:free", "openrouter/free"]))
    assert calls == ["a/x:free"]  # ayni kotaya bagli digerleri denenmedi
    assert orc.quota_status()["exhausted"] is True

    with pytest.raises(orc.OpenRouterQuotaError):
        asyncio.run(c.chat([], model="b/y:free"))
    assert calls == ["a/x:free"]  # ikinci cagri aga hic gitmedi


def test_paid_models_still_tried_when_free_quota_exhausted():
    c, calls = _client(lambda m: QUOTA_429 if m.endswith(":free") else "tamam")
    info = {}
    msg = asyncio.run(c.chat([], model="a/x:free", fallback_models=["anthropic/paid"], info=info))
    assert msg.content == "tamam" and calls == ["a/x:free", "anthropic/paid"]
    assert info["fallback"] is True


def test_other_429s_do_not_mark_quota():
    c, calls = _client(lambda m: RuntimeError("Error code: 429 - upstream busy"))
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(c.chat([], model="a/x:free", fallback_models=["b/y:free"]))
    assert not isinstance(exc.value, orc.OpenRouterQuotaError)
    assert calls == ["a/x:free", "b/y:free"] and orc.quota_status()["exhausted"] is False
