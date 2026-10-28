"""router/ cekirdegi: kurallar, siniflandirici, LLM yedegi, yedek zinciri, politika, log.

Dis API'ler ve gercek gomme modeli kullanilmaz: HashingEmbedder (kelime ozetleri) +
sahte LLM + sahte httpx.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from config.settings import get_settings
from router.classifier import PrototypeClassifier, TaskClassifier, load_trained, save_trained
from router.embedder import HashingEmbedder
from router.llm_fallback import LlmRouter
from router.log import RoutingLog
from router.registry import ModelRegistry
from router.router import RouteRequest, Router

EXAMPLES = {
    "task_types": {
        "kod": ["python kodu hata düzelt", "fonksiyon test yaz kodu", "kodu refactor et python"],
        "sohbet": ["nasılsın bugün", "bana fıkra anlat", "canım sıkıldı konuşalım"],
        "arastirma": ["kapsamlı araştırma yap kaynak", "son gelişmeleri araştır kaynak", "araştır ve karşılaştır kaynak"],
    },
    "difficulty": {
        "basit": ["nasılsın bugün", "bana fıkra anlat", "saat kaç"],
        "orta": ["python kodu hata düzelt", "fonksiyon test yaz kodu"],
        "zor": ["kapsamlı araştırma yap kaynak", "kodu refactor et python mimari kapsamlı"],
    },
    "agents": {
        "kodcu": ["python kodu yaz düzelt"],
        "arastirmaci": ["araştırma yap kaynak"],
        "hava_durumu": ["hava durumu yağmur"],
    },
}


def _registry() -> ModelRegistry:
    return ModelRegistry.load(get_settings().router_config_path)


def _router(tmp_path, *, llm=None, classifier=True, registry=None) -> Router:
    reg = registry or _registry()
    clf = None
    if classifier:
        clf = TaskClassifier(HashingEmbedder(4096), EXAMPLES, temperature=reg.temperature)
        clf.fit()
    return Router(reg, clf, llm, RoutingLog(tmp_path / "routing.jsonl"))


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ config
def test_models_yaml_is_valid_and_only_claude_is_paid():
    reg = _registry()
    assert reg.task_types and "qa" in reg.routes
    assert reg.chains["qa"][0] == "claude-opus-5-5"
    assert {m.id for m in reg.models.values() if m.paid} == {"claude-opus-5-5"}
    for name, chain in reg.chains.items():
        if name != "qa":
            assert not any(reg.get(m).paid for m in chain), f"{name} zincirinde ucretli model"


def test_invalid_chain_reference_is_rejected():
    with pytest.raises(ValueError):
        ModelRegistry({"models": [{"id": "a", "provider": "gemini"}], "chains": {"x": ["yok"]},
                       "routes": {}, "default_chain": "x"})


# ------------------------------------------------------------------ kurallar
def test_qa_rule_always_picks_strongest_model(tmp_path):
    d = run(_router(tmp_path).route(RouteRequest(text="bir sey", forced_task_type="qa")))
    assert d.source == "rule" and d.rule == "qa"
    assert d.model_id == "claude-opus-5-5" and d.difficulty == "zor"


def test_explicit_model_request_is_honoured_even_if_paid(tmp_path):
    d = run(_router(tmp_path).route(RouteRequest(text="bu raporu claude ile yap")))
    assert d.rule == "explicit_model" and d.model_id == "claude-opus-5-5"


def test_model_name_in_topic_is_not_an_explicit_request(tmp_path):
    d = run(_router(tmp_path).route(RouteRequest(text="gemini API'si hakkında kapsamlı araştırma yap kaynak")))
    assert d.rule is None
    assert d.model_id != "claude-opus-5-5"


def test_image_attachment_goes_to_vision_chain(tmp_path):
    reg = _registry()
    d = run(_router(tmp_path).route(RouteRequest(text="bunu oku", attachments=["ekran.png"])))
    assert d.rule == "image_attachment" and d.task_type == "gorsel"
    assert reg.get(d.model_id).has("vision")


def test_very_long_context_goes_to_long_context_chain(tmp_path):
    reg = _registry()
    d = run(_router(tmp_path).route(RouteRequest(text="özetle", context="x" * (reg.long_context_chars + 1))))
    assert d.rule == "long_context" and reg.get(d.model_id).has("long_context")


# ------------------------------------------------------------------ siniflandirici
def test_prototype_classifier_picks_nearest_class_with_margin_confidence():
    clf = PrototypeClassifier({"a": ["elma armut"], "b": ["araba otobüs"]}, temperature=0.008)
    emb = HashingEmbedder()
    clf.fit(emb)
    pred = clf.predict_vec(emb.embed(["elma armut"])[0])
    assert pred.label == "a" and pred.confidence > 0.99
    tie = clf.predict_vec(emb.embed(["bilinmeyen kelime"])[0])
    assert tie.confidence == pytest.approx(0.5)  # iki sinif esit uzaklikta -> kararsiz


def test_agent_candidates_restrict_the_choice():
    clf = PrototypeClassifier(EXAMPLES["agents"], temperature=0.008)
    emb = HashingEmbedder()
    clf.fit(emb)
    vec = emb.embed(["python kodu yaz"])[0]
    assert clf.predict_vec(vec).label == "kodcu"
    only = clf.predict_vec(vec, allowed={"hava_durumu"})
    assert only.label == "hava_durumu" and only.confidence == 1.0


def test_confident_classifier_decides_without_llm(tmp_path):
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        return "{}"

    llm = LlmRouter(ask, task_types=_registry().task_types)
    d = run(_router(tmp_path, llm=llm).route(RouteRequest(text="nasılsın bugün")))
    assert d.source == "classifier" and d.task_type == "sohbet" and d.difficulty == "basit"
    assert not calls and d.latency_ms < 1000


def test_unrelated_text_really_has_no_overlap():
    emb = HashingEmbedder(4096)
    words = [w for table in EXAMPLES.values() for texts in table.values() for t in texts for w in t.split()]
    sims = emb.embed(words) @ emb.embed(["tamamen alakasiz kelimeler xyz"])[0]
    assert float(sims.max()) == 0.0   # testlerdeki "dusuk guven" senaryosu gercekten kararsiz


def test_low_confidence_asks_llm_once(tmp_path):
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        return '{"task_type": "arastirma", "difficulty": "zor"}'

    llm = LlmRouter(ask, task_types=_registry().task_types)
    d = run(_router(tmp_path, llm=llm).route(RouteRequest(text="tamamen alakasiz kelimeler xyz")))
    assert len(calls) == 1 and d.source == "llm_fallback"
    assert (d.task_type, d.difficulty) == ("arastirma", "zor")


def test_llm_failure_is_reported_not_silent(tmp_path):
    async def ask(prompt):
        raise TimeoutError("yavas")

    llm = LlmRouter(ask, task_types=_registry().task_types)
    d = run(_router(tmp_path, llm=llm).route(RouteRequest(text="tamamen alakasiz kelimeler xyz")))
    assert d.source == "classifier"
    assert any("LLM yonlendirmesi basarisiz" in w for w in d.warnings)
    assert any("dusuk guvenli" in w for w in d.warnings)


def test_llm_invalid_json_is_rejected(tmp_path):
    async def ask(prompt):
        return '{"task_type": "uydurma", "difficulty": "zor"}'

    llm = LlmRouter(ask, task_types=_registry().task_types)
    d = run(_router(tmp_path, llm=llm).route(RouteRequest(text="tamamen alakasiz kelimeler xyz")))
    assert d.source != "llm_fallback" and d.warnings


def test_no_classifier_and_no_llm_uses_default_with_warning(tmp_path):
    d = run(_router(tmp_path, classifier=False).route(RouteRequest(text="merhaba")))
    assert d.source == "default" and d.chain
    assert any("siniflandirici hazir degil" in w for w in d.warnings)


# ------------------------------------------------------------------ zincir / yedek / politika
def test_inactive_primary_is_skipped_loudly(tmp_path):
    reg = _registry()
    first = reg.chains["hizli"][0]
    reg.mark(first, active=False, status="pasif", reason="listede yok")
    d = run(_router(tmp_path, registry=reg).route(RouteRequest(text="nasılsın bugün")))
    assert d.model_id != first and first not in d.chain
    assert any(first in w and "PASIF" in w for w in d.warnings)
    assert any("YEDEK" in w for w in d.warnings)


def test_all_models_inactive_falls_back_with_warning(tmp_path):
    reg = _registry()
    for model in reg.models:
        reg.mark(model, active=False, status="pasif", reason="test")
    d = run(_router(tmp_path, registry=reg).route(RouteRequest(text="nasılsın bugün")))
    assert d.chain and any("varsayilan" in w for w in d.warnings)


def test_paid_model_is_never_chosen_outside_policy(tmp_path):
    reg = _registry()
    reg.chains["hizli"] = ["claude-opus-5-5", *reg.chains["hizli"]]   # yanlis yapilandirma
    d = run(_router(tmp_path, registry=reg).route(RouteRequest(text="nasılsın bugün")))
    assert "claude-opus-5-5" not in d.chain
    assert "ucret politikasi" in d.reason


def test_paid_hint_from_claude_agent_is_allowed_and_first_for_hard_tasks(tmp_path):
    d = run(_router(tmp_path).route(RouteRequest(
        text="kapsamlı araştırma yap kaynak", hint_model="claude-opus-5-5")))
    assert d.difficulty == "zor" and d.chain[0] == "claude-opus-5-5"


def test_hint_goes_last_for_simple_tasks(tmp_path):
    hint = "poolside/laguna-s-2.1:free"
    d = run(_router(tmp_path).route(RouteRequest(text="nasılsın bugün", hint_model=hint)))
    assert d.difficulty == "basit" and d.chain[-1] == hint and d.chain[0] != hint


def test_registry_fallback_for_inactive_persona_model():
    reg = _registry()
    model = "poolside/laguna-s-2.1:free"
    reg.mark(model, active=False, status="pasif", reason="kaldirildi")
    backup = reg.fallback_for(model)
    assert backup and backup != model and reg.is_active(backup) and not reg.get(backup).paid


# ------------------------------------------------------------------ log
def test_decision_and_done_lines_are_written(tmp_path):
    router = _router(tmp_path)
    d = run(router.route(RouteRequest(text="x" * 500, request_id="r1")))
    router.record(d, "x" * 500)
    router.record_done("r1", ok=True, model_used=d.model_id, total_ms=12.0)
    rows = [json.loads(line) for line in (tmp_path / "routing.jsonl").read_text("utf-8").splitlines()]
    assert [r["kind"] for r in rows] == ["decision", "done"]
    first = rows[0]
    assert len(first["request"]) == 200
    for key in ("model_id", "source", "latency_ms", "scores", "chain", "task_type", "difficulty", "warnings"):
        assert key in first
    assert rows[1]["request_id"] == "r1" and rows[1]["total_ms"] == 12.0


# ------------------------------------------------------------------ erisilebilirlik
class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


def test_probe_marks_unreachable_models(monkeypatch):
    import httpx

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kw):
            if "openrouter" in url:   # laguna listede yok
                return _Resp({"data": [{"id": "nvidia/nemotron-3.5-super-vl:free"},
                                       {"id": "nvidia/nemotron-3-ultra-550b-a55b:free"}]})
            if "generativelanguage" in url:
                raise httpx.ConnectError("ag yok")
            if "11434" in url:
                raise httpx.ConnectError("ollama kapali")
            raise AssertionError(url)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    reg = _registry()
    report = asyncio.run(reg.probe(gemini_key="g", openrouter_key="o", anthropic_key=""))
    assert not reg.is_active("poolside/laguna-s-2.1:free")
    assert reg.is_active("nvidia/nemotron-3.5-super-vl:free")
    assert not reg.is_active("claude-opus-5-5") and "anahtari yok" in reg.get("claude-opus-5-5").reason
    gem = reg.get("gemini-flash-lite-latest")
    assert gem.active and gem.status == "dogrulanamadi"   # ag hatasi pasiflestirmez
    assert not reg.is_active("qwen2.5:7b")
    assert "poolside/laguna-s-2.1:free" in report["pasif"]


# ------------------------------------------------------------------ egitilmis model
def test_trained_model_roundtrip_without_pickle(tmp_path):
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(0)
    x = np.vstack([rng.normal(0, 1, (20, 8)) + 3, rng.normal(0, 1, (20, 8)) - 3, rng.normal(0, 1, (20, 8))])
    y = ["a"] * 20 + ["b"] * 20 + ["c"] * 20
    model = LogisticRegression(max_iter=500).fit(x, y)
    path = tmp_path / "m.npz"
    save_trained(path, {"task_types": model})
    heads = load_trained(path)
    pred = heads["task_types"].predict_vec(np.full(8, 3.0))
    assert pred.label == "a" and pred.method == "trained"
    np.testing.assert_allclose(heads["task_types"].proba(x[0]), model.predict_proba(x[:1])[0], atol=1e-6)


# ------------------------------------------------------------------ gorev tipi ajandan
def _agent_router(tmp_path, calls):
    async def ask(prompt):
        calls.append(prompt)
        return '{"task_type": "sohbet", "difficulty": "orta"}'

    reg = _registry()
    clf = TaskClassifier(HashingEmbedder(4096), EXAMPLES, temperature=reg.temperature)
    clf.fit()
    llm = LlmRouter(ask, task_types=reg.task_types)
    deps = {"kodcu": "gelistirme", "arastirmaci": "bilgi", "hava_durumu": "gunluk"}
    return Router(reg, clf, llm, RoutingLog(tmp_path / "r.jsonl"), deps)


def test_confident_agent_sets_task_type(tmp_path):
    calls = []
    d = run(_agent_router(tmp_path, calls).route(RouteRequest(text="hava durumu yağmur", pick_agent=True)))
    assert d.agent == "hava_durumu" and d.task_type == "sohbet"   # agent_task_types eslemesi
    assert "ajandan" in d.reason


def test_explicit_agent_name_sets_task_type(tmp_path):
    calls = []
    d = run(_agent_router(tmp_path, calls).route(RouteRequest(text="fonksiyon test yaz kodu", agent_name="arastirmaci")))
    assert d.task_type == "arastirma"   # departman eslemesi (bilgi -> arastirma)


def test_low_agent_confidence_defers_task_type_to_chosen_agent(tmp_path):
    calls = []
    router = _agent_router(tmp_path, calls)
    d = run(router.route(RouteRequest(text="tamamen alakasiz kelimeler xyz", pick_agent=True)))
    # gorev tipi Conductor'in sececegi ajandan gelecek: gorev tipi icin LLM'e sorulmaz
    assert all("difficulty" in c for c in calls)
    d = router.reroute_for_agent(d, agent="kodcu", hint=None, needs_tools=True,
                                 source="conductor_llm", confidence=0.9)
    assert d.task_type == "kod" and d.agent == "kodcu"


def test_confident_vision_classification_is_not_overridden_by_agent(tmp_path):
    reg = _registry()
    examples = {**EXAMPLES, "task_types": {**EXAMPLES["task_types"], "gorsel": ["fotoğraftaki yazıyı oku ekran"]}}
    clf = TaskClassifier(HashingEmbedder(4096), examples, temperature=reg.temperature)
    clf.fit()
    router = Router(reg, clf, None, RoutingLog(tmp_path / "r.jsonl"), {"kodcu": "gelistirme"})
    d = run(router.route(RouteRequest(text="fotoğraftaki yazıyı oku ekran", agent_name="kodcu")))
    assert d.task_type == "gorsel" and reg.get(d.model_id).has("vision")


def test_probe_rejected_anthropic_key_is_inactive_with_reason(monkeypatch):
    import httpx

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, **kw):
            if "anthropic" in url:
                assert headers.get("anthropic-workspace-id") == "ws-1"
                return _Resp({"error": {"message": "This API key is not scoped to a workspace"}}, 400)
            return _Resp({"data": [], "models": []})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    reg = _registry()
    asyncio.run(reg.probe(gemini_key="g", openrouter_key="o", anthropic_key="a", anthropic_workspace="ws-1"))
    claude = reg.get("claude-opus-5-5")
    assert not claude.active and "reddedildi" in claude.reason and "workspace" in claude.reason
