"""Zamanli gorevler: Turkce saat yorumu, schedule_task, tetikleme, orkestratorde not alma."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from config.settings import get_settings
from core.scheduler import Scheduler, add_task_record, parse_when

BASE = datetime(2026, 10, 3, 13, 0).astimezone()  # cumartesi 13:00


@pytest.mark.parametrize("text, expected", [
    ("saat 3", "03 15:00"),          # gunduz "saat 3" -> bugun 15:00 (eskiden yarin 03:00'tu)
    ("saat 3'te", "03 15:00"),
    ("3'te", "03 15:00"),
    ("saat 7", "03 19:00"),
    ("akşam 7", "03 19:00"),
    ("öğleden sonra 3", "03 15:00"),
    ("sabah 7", "04 07:00"),
    ("gece 2", "04 02:00"),
    ("gece 11", "03 23:00"),
    ("09:00", "04 09:00"),           # sifirla yazilmis saat belirsiz degil
    ("15:00", "03 15:00"),
    ("yarın saat 9", "04 09:00"),
    ("yarın saat 3", "04 15:00"),
    ("cuma saat 3", "09 15:00"),
    ("20 dakika sonra", "03 13:20"),
])
def test_parse_when_turkish_hours(text, expected):
    assert parse_when(text, BASE).strftime("%d %H:%M") == expected


def test_parse_when_rejects_garbage():
    assert parse_when("bilmem ne zaman", BASE) is None
    assert parse_when("saat 25", BASE) is None


@pytest.fixture
def dirs(tmp_path):
    return {"data": tmp_path, "outbox": tmp_path / "outbox.txt", "inbox": tmp_path / "inbox.txt"}


def test_scheduled_task_fires_into_agent_inbox(dirs):
    res = add_task_record(dirs["data"], "yapay zeka haberlerini analiz et", "15:00", save_note=True)
    assert res["status"] == "zamanli gorev kuruldu" and res["not_alinacak"] is True

    # vakti gelmis gibi yap
    path = dirs["data"] / "reminders.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items[0]["fire_at"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(timespec="seconds")
    path.write_text(json.dumps(items), encoding="utf-8")

    sched = Scheduler(dirs["data"], dirs["outbox"], dirs["inbox"], default_briefing=False)
    sched.tick_once()

    job = json.loads(dirs["inbox"].read_text(encoding="utf-8").strip())
    assert job["task"] == "yapay zeka haberlerini analiz et"
    assert job["source"] == "zamanli:not" and job["agent"] == "auto"
    assert "[ZAMANLI GOREV] Basladi" in dirs["outbox"].read_text(encoding="utf-8")
    assert "[HATIRLATICI]" not in dirs["outbox"].read_text(encoding="utf-8")

    sched.tick_once()  # ikinci kez tetiklenmez
    assert len(dirs["inbox"].read_text(encoding="utf-8").strip().splitlines()) == 1


def test_plain_reminder_still_speaks(dirs):
    from core.scheduler import add_reminder_record

    add_reminder_record(dirs["data"], "ders calisma vakti, masaya gec", "20 dakika sonra")
    path = dirs["data"] / "reminders.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items[0]["fire_at"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(timespec="seconds")
    path.write_text(json.dumps(items), encoding="utf-8")
    Scheduler(dirs["data"], dirs["outbox"], dirs["inbox"], default_briefing=False).tick_once()
    assert "[HATIRLATICI] ders calisma vakti" in dirs["outbox"].read_text(encoding="utf-8")
    assert not dirs["inbox"].exists()


def test_orchestrator_scheduled_task_skips_approval_and_saves_note(tmp_path, monkeypatch):
    from agents import orchestrator as orch_mod
    from agents.events import OrchestratorObserver
    from agents.schemas import AgentResult, TaskRequest

    settings = get_settings().model_copy(update={
        "agent_outbox_path": tmp_path / "outbox.txt", "agent_inbox_path": tmp_path / "inbox.txt",
        "agents_require_approval": True, "supabase_url": "", "ntfy_topic": "",
    })

    class DenyObserver(OrchestratorObserver):
        def confirm(self, prompt):  # noqa: ANN001 - onay istenirse REDDEDER
            raise AssertionError("zamanli gorevde onay sorulmamali")

    class FakeAgent:
        def __init__(self, spec, *a, **kw):  # noqa: ANN001, ANN002, ANN003
            self.spec = spec

        async def run(self, task, context=""):  # noqa: ANN001
            return AgentResult(ok=True, text="Analiz: uc onemli gelisme var.", model="m")

    notes: list[str] = []
    monkeypatch.setattr(orch_mod, "Agent", FakeAgent)
    monkeypatch.setattr("tools.basic_tools.remember_note",
                        lambda content: notes.append(content) or {"status": "kaydedildi"})

    orch = orch_mod.AgentOrchestrator(settings, observer=DenyObserver())
    agent_name = next(n for n, s in orch.agents.items() if s.autonomy.value == "human_assisted")
    req = TaskRequest(agent=agent_name, task="haberleri analiz et", source="zamanli:not")

    async def scenario():
        await orch._handle(req)
        await asyncio.sleep(0)  # supabase log gorevleri

    asyncio.run(scenario())
    assert notes and "haberleri analiz et" in notes[0] and "uc onemli gelisme" in notes[0]
    assert "uc onemli gelisme" in (tmp_path / "outbox.txt").read_text(encoding="utf-8")


def test_schedule_task_tool_registered_for_voice_and_agents():
    from agents.agent_tools import build_callables
    from tools.tool_runner import ToolRunner

    assert "schedule_task" in ToolRunner().tool_names
    assert "schedule_task" in {f.__name__ for f in build_callables(["schedule"])}


# ------------------------------------------------------------------ web arama yedegi
def test_web_research_falls_back_to_duckduckgo_and_blocks_grounding(monkeypatch):
    from tools import quick_tools as qt

    monkeypatch.setattr(qt, "_grounding_blocked_until", 0.0)
    calls = {"google": 0}

    def fake_grounded(q, n):  # noqa: ANN001
        calls["google"] += 1
        return {"error": "429 RESOURCE_EXHAUSTED"}

    monkeypatch.setattr(qt, "_grounded_research", fake_grounded)
    monkeypatch.setattr(qt, "duckduckgo_search",
                        lambda q, max_results=8: {"backend": "duckduckgo", "results": [{"title": q}]})
    first = qt.web_research("yapay zeka")
    second = qt.web_research("yapay zeka 2")
    assert first["backend"] == second["backend"] == "duckduckgo"
    assert calls["google"] == 1  # kota hatasindan sonra Google bir saat denenmez


def test_duckduckgo_sorts_news_and_drops_bad_dates(monkeypatch):
    import sys
    import types as pytypes

    from tools import quick_tools as qt

    class FakeDDGS:
        def news(self, q, **kw):  # noqa: ANN001, ANN003
            return [{"date": "2026-09-01T10:00", "title": "eski", "body": "", "url": "u1"},
                    {"date": "Opinion5 g", "title": "bozuk", "body": "", "url": "u2"},
                    {"date": "2026-10-02T09:00", "title": "yeni", "body": "", "url": "u3"}]

        def text(self, q, **kw):  # noqa: ANN001, ANN003
            return [{"title": "web", "body": "", "href": "u4"}]

    monkeypatch.setitem(sys.modules, "ddgs", pytypes.SimpleNamespace(DDGS=FakeDDGS))
    res = qt.duckduckgo_search("x")
    assert [r["title"] for r in res["results"]][:2] == ["yeni", "eski"]
    assert next(r for r in res["results"] if r["title"] == "bozuk")["date"] == ""


def test_researcher_has_web_search_and_no_dead_grounding():
    from pathlib import Path

    from agents.agent_tools import build_callables
    from agents.registry import load_agents

    spec = load_agents(Path("agents/agents.json"))["arastirmaci"]
    assert "web_search" in spec.capabilities and spec.grounded_search is False
    assert [f.__name__ for f in build_callables(spec.capabilities)] == ["search_web"]
