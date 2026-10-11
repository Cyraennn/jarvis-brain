"""SchedulerHandler + NotificationBroadcaster + proaktif kanal gonderimleri - agsiz testler."""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from config.settings import get_settings
from core.notifications import NotificationBroadcaster
from core.scheduler_handler import SchedulerHandler, overnight_task_results, parse_hhmm


@pytest.fixture
def settings(tmp_path):
    return get_settings().model_copy(update={
        "data_dir": tmp_path,
        "bridge_outbox_path": tmp_path / "outbox.txt",
        "agent_outbox_path": tmp_path / "outbox.txt",
        "agent_inbox_path": tmp_path / "inbox.txt",
        "scheduler_enabled": True,
        "scheduler_tick": 5.0,
        "morning_briefing_time": "08:30",
        "morning_briefing_channels": [],
        "health_check_interval_min": 60,
        "openrouter_api_key": "",
        "gemini_api_key": "",
        "telegram_bot_token": "",
        "ntfy_topic": "",
    })


class Recorder(NotificationBroadcaster):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, list | None]] = []

    async def broadcast(self, text, channels=None):  # noqa: ANN001
        self.sent.append((text, channels))
        return {"test": True}


# ------------------------------------------------------------------ yardimcilar
@pytest.mark.parametrize("raw, expected", [
    ("08:30", (8, 30)), ("8.05", (8, 5)), ("7", (7, 0)),
    ("", None), ("kapali", None), ("25:00", None), ("abc", None),
])
def test_parse_hhmm(raw, expected):
    assert parse_hhmm(raw) == expected


def test_broadcaster_isolates_failing_and_slow_channels(monkeypatch):
    from core import notifications

    monkeypatch.setattr(notifications, "SEND_TIMEOUT_S", 0.2)
    b = NotificationBroadcaster()

    async def ok(_t):
        return True

    async def boom(_t):
        raise RuntimeError("kanal coktu")

    async def slow(_t):
        await asyncio.sleep(5)
        return True

    for name, fn in (("ok", ok), ("boom", boom), ("slow", slow)):
        b.register(name, fn)
    result = asyncio.run(b.broadcast("selam"))
    assert result == {"ok": True, "boom": False, "slow": False}
    assert asyncio.run(b.broadcast("selam", ["yok"])) == {}


# ------------------------------------------------------------------ yasam dongusu
def test_run_registers_jobs_and_shuts_down_cleanly(settings):
    handler = SchedulerHandler(settings, broadcaster=Recorder())

    async def scenario():
        task = asyncio.create_task(handler.run())
        await asyncio.sleep(0.3)
        jobs = {j.split("@")[0] for j in handler.describe_jobs()}
        sched = handler._scheduler
        handler.request_shutdown()
        await asyncio.wait_for(task, 3)
        return jobs, sched

    jobs, sched = asyncio.run(scenario())
    assert jobs == {"reminders", "morning_briefing", "health_check", "maintenance_report",
                    "daily_summary", "daily_summary_catchup"}
    assert not sched.running and handler._scheduler is None


def test_cancel_also_shuts_scheduler_down(settings):
    handler = SchedulerHandler(settings, broadcaster=Recorder())

    async def scenario():
        task = asyncio.create_task(handler.run())
        await asyncio.sleep(0.3)
        sched = handler._scheduler
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return sched

    assert not asyncio.run(scenario()).running


def test_disabled_handler_returns_immediately(settings):
    handler = SchedulerHandler(settings.model_copy(update={"scheduler_enabled": False}))
    asyncio.run(asyncio.wait_for(handler.run(), 1))
    assert handler._scheduler is None


def test_request_shutdown_from_other_thread(settings):
    handler = SchedulerHandler(settings, broadcaster=Recorder())

    async def scenario():
        task = asyncio.create_task(handler.run())
        await asyncio.sleep(0.3)
        threading.Thread(target=handler.request_shutdown).start()
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())


def test_crashing_job_is_isolated(settings):
    handler = SchedulerHandler(settings, broadcaster=Recorder())

    async def boom():
        raise ValueError("is coktu")

    asyncio.run(handler._guarded("boom", boom)())  # istisna yukari tasinmaz


def test_morning_briefing_disables_legacy_routine(settings):
    handler = SchedulerHandler(settings, broadcaster=Recorder())
    handler._make_legacy_scheduler()
    routines = json.loads((settings.data_dir / "routines.json").read_text(encoding="utf-8"))
    assert next(r for r in routines if r["id"] == "daily_briefing")["enabled"] is False

    off = SchedulerHandler(settings.model_copy(update={"morning_briefing_time": "kapali"}),
                           broadcaster=Recorder())
    off._make_legacy_scheduler()
    routines = json.loads((settings.data_dir / "routines.json").read_text(encoding="utf-8"))
    assert next(r for r in routines if r["id"] == "daily_briefing")["enabled"] is True


# ------------------------------------------------------------------ isler
def test_morning_briefing_falls_back_to_template(settings, monkeypatch):
    rec = Recorder()
    handler = SchedulerHandler(settings, broadcaster=rec)
    facts = {"tarih": "03.10.2026 Cumartesi",
             "hava": {"konum": "Izmir", "simdi": {"sicaklik": 23, "durum": "acik"}, "bugun": {}},
             "hatirlaticilar": ["14:00 dis hekimi"]}
    monkeypatch.setattr(handler, "collect_briefing_facts", lambda: facts)
    text = asyncio.run(handler.morning_briefing())
    assert "Gunaydin" in text and "dis hekimi" in text and "23" in text
    assert rec.sent == [(text, None)]


def test_health_check_alerts_once_per_cooldown(settings, monkeypatch):
    rec = Recorder()
    handler = SchedulerHandler(settings, broadcaster=rec)
    monkeypatch.setattr(handler, "system_snapshot",
                        lambda: {"cpu": 97.0, "mem": 40.0, "disk": 50.0, "brain_session": None})
    first = asyncio.run(handler.health_check())
    second = asyncio.run(handler.health_check())
    assert first["alerts"] and not second["alerts"]
    assert len(rec.sent) == 1 and "CPU %97" in rec.sent[0][0]


def test_reminder_job_fires_due_reminder(settings):
    from datetime import datetime, timedelta

    due = (datetime.now().astimezone() - timedelta(seconds=5)).isoformat(timespec="seconds")
    (settings.data_dir / "reminders.json").write_text(
        json.dumps([{"id": "r1", "text": "ilac ic", "fire_at": due, "done": False}]), encoding="utf-8")
    handler = SchedulerHandler(settings, broadcaster=Recorder())
    asyncio.run(handler.check_reminders())
    assert "[HATIRLATICI] ilac ic" in settings.bridge_outbox_path.read_text(encoding="utf-8")


# ------------------------------------------------------------------ kanallar
def test_telegram_send_proactive_message_uses_default_chat(settings, monkeypatch):
    from core import telegram_handler

    posted = {}

    class FakeClient:
        def __init__(self, **kw):  # noqa: ANN003
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):  # noqa: ANN002
            return False

        async def post(self, url, json):  # noqa: A002, ANN001
            posted.update(json)
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(telegram_handler.httpx, "AsyncClient", FakeClient)
    s = settings.model_copy(update={"telegram_bot_token": "1:x", "telegram_default_chat_id": "42"})
    handler = telegram_handler.TelegramHandler(s)
    assert asyncio.run(handler.send_proactive_message(None, "gunaydin")) is True
    assert posted == {"chat_id": "42", "text": "gunaydin"}
    assert handler._memory.history("42")[-1]["text"] == "gunaydin"


def _wa_handler(settings):
    from core.whatsapp_handler import WhatsAppHandler, WhatsAppConfig

    cfg = WhatsAppConfig()
    cfg.enabled = True
    return WhatsAppHandler(settings, cfg, notifier=SimpleNamespace())


def test_whatsapp_proactive_queue_same_and_other_thread(settings, monkeypatch):
    handler = _wa_handler(settings)
    sent: list[tuple[str, str]] = []

    async def fake_send(page, number, text):  # noqa: ANN001
        sent.append((number, text))
        return True

    monkeypatch.setattr(handler, "_send_to_number", fake_send)

    async def scenario():
        handler._loop = asyncio.get_running_loop()
        handler._outgoing = asyncio.Queue()

        async def pump():  # yoklama dongusunu taklit eder
            for _ in range(100):
                await handler._drain_outgoing(page=None)
                await asyncio.sleep(0.01)

        pump_task = asyncio.create_task(pump())
        same = await handler.send_proactive_message("+90 555 111 22 33", "ayni dongu")
        other = await asyncio.to_thread(
            lambda: asyncio.run(handler.send_proactive_message("905551112233", "baska thread")))
        pump_task.cancel()
        return same, other

    assert asyncio.run(scenario()) == (True, True)
    assert [t for _, t in sent] == ["ayni dongu", "baska thread"]


def test_whatsapp_proactive_skipped_when_not_running(settings):
    handler = _wa_handler(settings)
    assert asyncio.run(handler.send_proactive_message("905551112233", "x")) is False


def test_overnight_task_results_reads_window_and_body(tmp_path):
    from datetime import datetime

    (tmp_path / "2026-10-04.md").write_text(
        "# JARVIS Notlari\n\n"
        "- **12:00** Zamanli gorev (Eski): ogle gorevi\n  \n  sayilmamali\n"
        "- **23:00** Zamanli gorev (Sistem Sagligi): disk raporu\n  \n  Disk %97 dolu.\n  Temizlik onerildi.\n",
        encoding="utf-8")
    (tmp_path / "2026-10-05.md").write_text(
        "- **01:30** baska bir not\n"
        "- **03:31** Zamanli gorev (Arastirmaci): Dart\n  \n  " + "x" * 500 + "\n"
        "- **09:00** Zamanli gorev (Gelecek): henuz degil\n  \n  yok\n",
        encoding="utf-8")
    got = overnight_task_results(datetime(2026, 10, 5, 8, 30), notes_dir=tmp_path)
    assert [g["ajan"] for g in got] == ["Sistem Sagligi", "Arastirmaci"]
    assert got[0]["sonuc"] == "Disk %97 dolu. Temizlik onerildi."
    assert got[1]["saat"] == "03:31" and got[1]["sonuc"].endswith("...")


def test_template_briefing_lists_overnight_tasks():
    text = SchedulerHandler.template_briefing({
        "tarih": "05.10.2026 Pazartesi",
        "gece_gorevleri": [{"ajan": "Sistem Sagligi"}, {"ajan": "Arastirmaci"}],
    })
    assert "Gece 2 gorev tamamlandi: Sistem Sagligi, Arastirmaci" in text
