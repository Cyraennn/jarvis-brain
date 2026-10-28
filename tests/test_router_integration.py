"""Router entegrasyonu: orkestrator, onay kapisi, Conductor yedegi, Veronica QA, Stark ekibi,
Agent zincir sirasi. Dis API yok: sahte gomme, sahte ajan, sahte LLM/QA.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import fields

import pytest

from agents.events import OrchestratorObserver
from agents.schemas import AgentResult, RoutingDecision, TaskRequest
from config.settings import get_settings
from router import RouteDecision, build_router
from router.embedder import HashingEmbedder

HARD = "Dart programlama dili hakkında kapsamlı bir araştırma yap ve Türkçe ders notu hazırla"


def _settings(tmp_path, **extra):
    base = {
        "router_enabled": True, "agent_outbox_path": tmp_path / "outbox.txt",
        "agent_inbox_path": tmp_path / "inbox.txt", "routing_log_path": tmp_path / "routing.jsonl",
        "router_model_path": tmp_path / "yok.npz", "agents_require_approval": False,
        "supabase_url": "", "ntfy_topic": "",
    }
    base.update(extra)
    return get_settings().model_copy(update=base)


async def _no_llm(prompt):  # dusuk guvende router'in sordugu LLM - testte hep basarisiz
    raise TimeoutError("testte LLM yok")


@pytest.fixture(scope="module")
def _base_orch(tmp_path_factory):
    """Orkestrator kurulumu (API istemcileri) ~4 sn surer: dosya basina BIR kez kurulur;
    her test kendi router'ini, ayarlarini ve sahtelerini takar."""
    from unittest import mock

    from agents import orchestrator as orch_mod

    with mock.patch.object(orch_mod.AgentOrchestrator, "_make_router", lambda self: None):
        return orch_mod.AgentOrchestrator(_settings(tmp_path_factory.mktemp("orch")))


@pytest.fixture
def make_orch(_base_orch, tmp_path, monkeypatch):
    from agents import orchestrator as orch_mod
    from agents.qa import QaVerdict

    def factory(*, llm_ask=_no_llm, observer=None, agent_cls=None, **extra):
        settings = _settings(tmp_path, **extra)
        router = build_router(settings, agents=_base_orch.agents, llm_ask=llm_ask,
                              embedder=HashingEmbedder(4096))
        router.classifier.fit()
        orch = _base_orch
        monkeypatch.setattr(orch, "settings", settings)
        monkeypatch.setattr(orch, "router", router)
        monkeypatch.setattr(orch, "observer", observer or OrchestratorObserver())
        monkeypatch.setattr(orch, "_sem", asyncio.Semaphore(3))
        if agent_cls is not None:
            monkeypatch.setattr(orch_mod, "Agent", agent_cls)

        async def offline_qa(task, result, chain, request_id=""):
            # Gercek Veronica (ucretli Claude) testte ASLA cagrilmasin; QA testleri kendi sahtesini verir.
            return QaVerdict(True, model="sahte-qa")

        monkeypatch.setattr(orch.qa, "review", offline_qa)
        return orch

    return factory


class RecordingAgent:
    runs: list[dict] = []

    def __init__(self, spec, *a, model_chain=None, **kw):
        self.spec, self.model_chain = spec, model_chain

    async def run(self, task, context=""):
        RecordingAgent.runs.append({"agent": self.spec.name, "chain": self.model_chain, "context": context})
        return AgentResult(ok=True, text=f"sonuc {len(RecordingAgent.runs)}",
                           model=(self.model_chain or ["?"])[0])


@pytest.fixture(autouse=True)
def _reset_runs():
    RecordingAgent.runs = []


def _handle(orch, **req):
    async def scenario():
        await orch._handle(TaskRequest(**req))
        await asyncio.sleep(0)
    asyncio.run(scenario())


def _log(tmp_path):
    path = tmp_path / "routing.jsonl"
    return [json.loads(x) for x in path.read_text("utf-8").splitlines()] if path.exists() else []


def _outbox(tmp_path):
    path = tmp_path / "outbox.txt"
    return path.read_text("utf-8") if path.exists() else ""


# ------------------------------------------------------------------ uctan uca
def test_auto_task_is_routed_locally_and_logged(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)

    async def no_conductor(*a, **kw):
        raise AssertionError("yerel karar yeterliyken Conductor LLM cagrilmamali")

    monkeypatch.setattr(orch.conductor, "route", no_conductor)
    _handle(orch, task="yarın hangi derslerim var")
    assert RecordingAgent.runs[0]["agent"] == "ders_programi"
    chain = RecordingAgent.runs[0]["chain"]
    assert chain and chain[0] == orch.router.registry.chains["hizli"][0]
    kinds = [r["kind"] for r in _log(tmp_path)]
    assert kinds == ["decision", "done"]
    decision, done = _log(tmp_path)
    assert decision["agent"] == "ders_programi" and decision["agent_source"] == "classifier"
    assert done["model_used"] == chain[0] and done["total_ms"] >= 0


def test_explicit_agent_keeps_its_paid_hint_first_for_hard_work(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    monkeypatch.setattr(orch, "_qa_due", lambda route: False)
    _handle(orch, agent="kodcu", task=HARD)
    run = RecordingAgent.runs[0]
    assert run["agent"] == "kodcu" and run["chain"][0] == "claude-opus-5-5"
    assert _log(tmp_path)[0]["agent_source"] == "explicit"


def test_department_hint_restricts_agent_choice(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    _handle(orch, agent="okul", task="geciken ödevlerimi listele")
    assert orch.agents[RecordingAgent.runs[0]["agent"]].department.value == "okul"


def test_low_agent_confidence_asks_conductor_llm(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    asked = []

    async def conductor(task, context=""):
        asked.append(task)
        return RoutingDecision(agent="hava_durumu", reason="llm secti", confidence=0.9)

    monkeypatch.setattr(orch.conductor, "route", conductor)
    _handle(orch, task="qqq zzz www")
    assert asked and RecordingAgent.runs[0]["agent"] == "hava_durumu"
    assert _log(tmp_path)[0]["agent_source"] == "conductor_llm"


def test_conductor_failure_keeps_local_choice_with_warning(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)

    async def broken(task, context=""):
        return RoutingDecision(agent="ders_programi", reason="[YEDEK YONLENDIRME - model yok] x", confidence=0.2)

    monkeypatch.setattr(orch.conductor, "route", broken)
    _handle(orch, task="qqq zzz www")
    decision = _log(tmp_path)[0]
    assert any("Conductor LLM yanit vermedi" in w for w in decision["warnings"])


def test_router_disabled_uses_old_conductor_path(make_orch, tmp_path, monkeypatch):
    from agents import orchestrator as orch_mod

    settings = _settings(tmp_path, router_enabled=False)
    monkeypatch.setattr(orch_mod, "Agent", RecordingAgent)
    orch = orch_mod.AgentOrchestrator(settings)   # gercek _make_router
    assert orch.router is None
    asked = []

    async def conductor(task, context=""):
        asked.append(task)
        return RoutingDecision(agent="ders_programi", reason="eski yol", confidence=0.9)

    monkeypatch.setattr(orch.conductor, "route", conductor)
    _handle(orch, task="yarın hangi derslerim var")
    assert asked and RecordingAgent.runs[0]["chain"] is None   # agents.json modelleri
    assert not _log(tmp_path)


def test_real_make_router_builds_and_activates(make_orch, tmp_path, monkeypatch):
    import router as router_pkg
    from agents import orchestrator as orch_mod

    orch = orch_mod.AgentOrchestrator(_settings(tmp_path))
    assert orch.router is not None and router_pkg.get_active() is orch.router


# ------------------------------------------------------------------ onay atlanamaz
class DenyObserver(OrchestratorObserver):
    asked: list[str] = []

    def confirm(self, prompt):
        DenyObserver.asked.append(prompt)
        return False


def test_router_cannot_bypass_human_assisted_approval(make_orch, tmp_path, monkeypatch):
    DenyObserver.asked = []
    orch = make_orch(agent_cls=RecordingAgent, observer=DenyObserver(),
                 agents_require_approval=True)
    _handle(orch, task="hocama bir e-posta yanıtı taslağı hazırla")
    chosen = _log(tmp_path)[0]["agent"]
    assert orch.agents[chosen].autonomy.value == "human_assisted"
    assert DenyObserver.asked, "onay sorulmadi"
    assert RecordingAgent.runs == [] and "onaylanmadi" in _outbox(tmp_path)


def test_router_cannot_start_human_led_agent(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    _handle(orch, task="gelen kutusunu temizle, silinecek toplu mailleri bul")
    assert _log(tmp_path)[0]["agent"] == "gelen_kutusu"
    assert RecordingAgent.runs == [] and "Insan Odakli" in _outbox(tmp_path)


def test_risky_tool_still_asks_for_confirmation_with_router_active(make_orch, tmp_path, monkeypatch):
    import router as router_pkg
    from tools import tool_runner as tr

    router_pkg.set_active(make_orch().router)
    monkeypatch.setattr(tr, "empty_recycle_bin", lambda: pytest.fail("onaysiz calisti"))
    asked = []
    runner = tr.ToolRunner(confirm=lambda prompt: asked.append(prompt) or False)
    out = runner._tool_empty_recycle_bin()
    assert asked and out["status"] == "iptal edildi"


def test_route_decision_carries_no_approval_or_tool_fields():
    names = {f.name for f in fields(RouteDecision)}
    assert not {n for n in names if any(k in n for k in ("confirm", "approv", "tool", "autonomy"))}


# ------------------------------------------------------------------ Veronica QA
def _qa_orch(make_orch, monkeypatch, verdicts):
    from agents.qa import QaVerdict

    orch = make_orch(agent_cls=RecordingAgent)
    seen = []
    queue = list(verdicts)

    async def review(task, result, chain, request_id=""):
        seen.append(chain)
        approved = queue.pop(0)
        return QaVerdict(approved, issues=["kaynak eksik"] if approved is False else [],
                         model=chain[0] if approved is not None else None)

    monkeypatch.setattr(orch.qa, "review", review)
    return orch, seen


def test_qa_runs_on_hard_tasks_with_strongest_model(make_orch, tmp_path, monkeypatch):
    orch, seen = _qa_orch(make_orch, monkeypatch, [True])
    _handle(orch, agent="arastirmaci", task=HARD)
    assert seen and seen[0][0] == "claude-opus-5-5"
    assert "[QA onayli]" in _outbox(tmp_path)
    assert any(r["kind"] == "qa" and r["approved"] is True for r in _log(tmp_path))


def test_qa_rejection_reruns_agent_once_with_feedback(make_orch, tmp_path, monkeypatch):
    orch, seen = _qa_orch(make_orch, monkeypatch, [False, False])
    _handle(orch, agent="arastirmaci", task=HARD)
    assert len(RecordingAgent.runs) == 2 and len(seen) == 2   # en fazla bir yeniden deneme
    assert "kaynak eksik" in RecordingAgent.runs[1]["context"]
    assert "QA ONAYLANMADI" in _outbox(tmp_path)


def test_qa_unavailable_is_reported_not_silent(make_orch, tmp_path, monkeypatch):
    orch, _ = _qa_orch(make_orch, monkeypatch, [None])
    _handle(orch, agent="arastirmaci", task=HARD)
    assert "QA YAPILAMADI" in _outbox(tmp_path)


def test_qa_skipped_for_simple_tasks(make_orch, tmp_path, monkeypatch):
    orch, seen = _qa_orch(make_orch, monkeypatch, [])
    _handle(orch, task="yarın hangi derslerim var")
    assert _log(tmp_path)[0]["difficulty"] == "basit" and not seen


def test_veronica_falls_back_loudly_when_claude_fails():
    from agents.qa import VeronicaQA

    class Claude:
        available = True

        async def create(self, *a, **kw):
            raise RuntimeError("529 overloaded")

    class Router:
        available = True

        async def generate_response(self, prompt, **kw):
            return '{"onay": true, "sorunlar": [], "ozet": "iyi"}'

    qa = VeronicaQA(claude=Claude(), openrouter=Router(), genai_client=None)
    verdict = asyncio.run(qa.review("gorev", "sonuc", ["claude-opus-5-5", "nvidia/nemotron-3-ultra-550b-a55b:free"]))
    assert verdict.approved is True and verdict.fallback is True
    assert verdict.model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert verdict.errors and "claude-opus-5-5" in verdict.errors[0]


# ------------------------------------------------------------------ Stark ekibi
def test_persona_keeps_model_unless_inactive(make_orch, tmp_path, monkeypatch):
    import router as router_pkg
    from agents import stark_team

    router = make_orch().router
    router_pkg.set_active(router)
    seen = []

    async def handler(p, text, history):
        seen.append(p.model)
        return {"text": "tamam", "model": p.model}

    monkeypatch.setitem(stark_team._HANDLERS, "openrouter", handler)
    monkeypatch.setitem(stark_team._HANDLERS, "gemini", handler)
    karen = stark_team.PERSONAS["karen"]

    out = asyncio.run(stark_team._ask_once(karen, "selam", []))
    assert seen[-1] == karen.model and "fallback" not in out

    router.registry.mark(karen.model, active=False, status="pasif", reason="kaldirildi")
    out = asyncio.run(stark_team._ask_once(karen, "selam", []))
    assert seen[-1] != karen.model
    assert out["text"].startswith("[YEDEK:") and karen.model in out["fallback"]


# ------------------------------------------------------------------ Agent zincir sirasi
def test_agent_honours_router_chain_order_and_marks_fallback(monkeypatch):
    from agents.agent import Agent
    from agents.registry import load_agents

    spec = load_agents(get_settings().agent_config_path)["hava_durumu"]
    agent = Agent(spec, None, default_models=["gemini-flash-lite-latest"], default_max_steps=2,
                  model_chain=["gemini-flash-lite-latest", "nvidia/nemotron-3.5-super-vl:free"])
    assert agent.provider_order == ["gemini", "openrouter"]

    async def gemini_fails(text, artifact, meta):
        return AgentResult(ok=False, text="", error="503")

    async def openrouter_ok(text, artifact):
        return AgentResult(ok=True, text="yanit", model="nvidia/nemotron-3.5-super-vl:free")

    monkeypatch.setattr(agent, "_run_gemini", gemini_fails)
    monkeypatch.setattr(agent, "_run_openrouter", openrouter_ok)
    result = asyncio.run(agent.run("hava nasil"))
    assert result.ok and result.fallback and result.primary_model == "gemini-flash-lite-latest"


def test_agent_without_chain_keeps_old_provider_order():
    from agents.agent import Agent
    from agents.registry import load_agents

    spec = load_agents(get_settings().agent_config_path)["kodcu"]
    agent = Agent(spec, None, default_models=["gemini-flash-lite-latest"], default_max_steps=2)
    assert agent.provider_order == ["claude", "openrouter", "gemini"]


def test_unrun_tasks_are_logged_as_done_with_status(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    _handle(orch, task="gelen kutusunu temizle, silinecek toplu mailleri bul")
    done = [r for r in _log(tmp_path) if r["kind"] == "done"]
    assert done and done[0]["status"] == "blocked" and done[0]["ok"] is False


def test_done_line_carries_estimated_cost(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    monkeypatch.setattr(orch, "_qa_due", lambda route: False)
    _handle(orch, agent="kodcu", task=HARD)                        # zincir basi claude (ucretli)
    done = [r for r in _log(tmp_path) if r["kind"] == "done"][0]
    assert done["model_used"] == "claude-opus-5-5" and done["est_cost_usd"] > 0
    _handle(orch, task="yarın hangi derslerim var")                 # ucretsiz model
    done = [r for r in _log(tmp_path) if r["kind"] == "done"][-1]
    assert done["est_cost_usd"] == 0.0


def test_explicit_model_rule_still_takes_task_type_from_agent(make_orch, tmp_path, monkeypatch):
    orch = make_orch(agent_cls=RecordingAgent)
    _handle(orch, agent="mesaj_yazari", task="nemotron ile sınıf grubuna duyuru metni hazırla")
    decision = _log(tmp_path)[0]
    assert decision["rule"] == "explicit_model" and decision["task_type"] == "yazi"
    assert decision["model_id"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
