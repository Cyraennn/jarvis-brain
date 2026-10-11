"""Gun sonu ozeti: kaynak toplama, dosya bicimi, telafi, sabah brifingi baglantisi."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta

import pytest

from config.settings import get_settings
from core import daily_summary as ds
from core.notifications import NotificationBroadcaster
from core.scheduler_handler import SchedulerHandler

DAY = date(2026, 10, 6)


@pytest.fixture
def settings(tmp_path):
    vault = tmp_path / "kasa"
    vault.mkdir()
    return get_settings().model_copy(update={
        "data_dir": tmp_path, "obsidian_vault": str(vault), "obsidian_subdir": "",
        "bridge_outbox_path": tmp_path / "outbox.txt", "agent_outbox_path": tmp_path / "outbox.txt",
        "agent_inbox_path": tmp_path / "inbox.txt", "scheduler_enabled": True,
        "morning_briefing_time": "08:30", "daily_summary_time": "23:30",
        "openrouter_api_key": "sk-or-test", "gemini_api_key": "", "ntfy_topic": "",
        "telegram_bot_token": "",
    })


def _seed(settings, day: date = DAY) -> None:
    vault = settings.obsidian_dir
    stamp = f"{day:%Y-%m-%d}"
    for sub, text in (
        ("Konusmalar", "---\ntags: [jarvis]\n---\n\n# Konusma\n\n**16:55 · Sen:** Mikrofonu ac\n\n"
                       "**16:56 · JARVIS:** Actim efendim.\n"),
        ("Notlar", "---\ntags: [jarvis]\n---\n\n# JARVIS Notlari\n\n- **17:00** Sut al\n"),
    ):
        (vault / sub).mkdir(exist_ok=True)
        (vault / sub / f"{stamp}.md").write_text(text, encoding="utf-8")
    rows = [
        {"id": "a1", "agent": "web_operatoru", "status": "running", "result": None,
         "updated_at": f"{stamp}T23:50:00+03:00"},
        {"id": "a1", "agent": "web_operatoru", "status": "done", "result": "ESHOT duyurusu bulundu",
         "updated_at": f"{stamp}T23:51:00+03:00"},
        {"id": "b2", "agent": "arastirmaci", "status": "done", "result": "baska gun",
         "updated_at": "2026-10-05T10:00:00+03:00"},
    ]
    (settings.data_dir / "task_logs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\nbozuk satir\n", encoding="utf-8")
    (settings.data_dir / "reminders.json").write_text(json.dumps(
        [{"fire_at": f"{stamp}T18:30:00", "text": "ilac", "done": True}]), encoding="utf-8")


def test_collects_only_that_days_records(settings):
    _seed(settings)
    facts = ds.collect_day_facts(DAY, vault=settings.obsidian_dir, data_dir=settings.data_dir)
    assert "Mikrofonu ac" in facts["konusma"] and "tags:" not in facts["konusma"]
    assert "Sut al" in facts["notlar"]
    assert facts["gorevler"] == [  # ayni gorevin son durumu, baska gun yok
        {"ajan": "web_operatoru", "durum": "done", "sonuc": "ESHOT duyurusu bulundu"}]
    assert facts["hatirlaticilar"] == ["18:30 ilac"]
    assert ds.has_content(facts)


def test_empty_day_writes_nothing(settings):
    assert asyncio.run(ds.run(settings, DAY)) is None
    assert not (settings.obsidian_dir / "Gunluk").exists()


def test_long_conversation_keeps_head_and_tail():
    text = "A" * 10_000 + "B" * 30_000 + "C" * 10_000
    clipped = ds._clip_conversation(text)
    assert len(clipped) < 25_000 and clipped.startswith("A") and clipped.endswith("C")
    assert "kisaltildi" in clipped


def test_template_summary_when_no_model_and_file_format(settings):
    _seed(settings)
    path = asyncio.run(ds.run(settings, DAY))  # gemini anahtari yok -> sablon
    text = path.read_text(encoding="utf-8")
    assert path == settings.obsidian_dir / "Gunluk" / "2026-10-06.md"
    assert "model: sablon" in text and "# Gün sonu özeti - 06.10.2026" in text
    for name in ds.SECTIONS:
        assert f"## {name}" in text
    assert "ESHOT duyurusu bulundu" in ds.read_section(path, "Yapılanlar")
    assert "Sut al" in ds.read_section(path, "Notlar")
    assert ds.read_section(path, "Açık kalanlar") == ""  # '- yok' bos sayilir


def test_model_summary_is_normalized_and_overwrites(settings, monkeypatch):
    _seed(settings)
    answers = iter(["Duz metin, baslik yok.",
                    "```markdown\n## Özet\nIyi gun.\n\n## Açık kalanlar\n- Rapor yarin\n```"])
    seen: list[str] = []

    async def fake(_settings, system, prompt, **_kw):
        seen.append(prompt)
        return next(answers), "gemini-test"

    monkeypatch.setattr("agents.genai_util.quick_text", fake)
    path = asyncio.run(ds.run(settings, DAY))
    assert ds.read_section(path, "Özet") == "Duz metin, baslik yok."
    path = asyncio.run(ds.run(settings, DAY))  # ayni gun tekrar: uzerine yazar
    assert ds.read_section(path, "Özet") == "Iyi gun."
    assert ds.read_section(path, "Açık kalanlar") == "- Rapor yarin"
    assert ds.read_section(path, "Notlar") == "" and "model: gemini-test" in path.read_text("utf-8")
    assert "Mikrofonu ac" in seen[0]


def test_raw_conversation_never_goes_to_openrouter(settings, monkeypatch):
    _seed(settings)  # openrouter anahtari VAR

    def boom(*a, **k):
        raise AssertionError("gun sonu ozeti OpenRouter'a gitmemeli")

    monkeypatch.setattr("core.openrouter_client.OpenRouterClient.__init__", boom)
    assert asyncio.run(ds.run(settings, DAY)) is not None


def test_catchup_only_when_yesterday_has_records_and_no_summary(settings):
    yesterday = (datetime.now() - timedelta(days=1)).date()
    handler = SchedulerHandler(settings, broadcaster=NotificationBroadcaster())
    assert asyncio.run(handler.daily_summary_catchup()) is None  # kayit yok
    _seed(settings, yesterday)
    assert ds.missing_for(settings, yesterday)
    path = asyncio.run(handler.daily_summary_catchup())
    assert path is not None and path.exists() and not ds.missing_for(settings, yesterday)
    stamp = path.stat().st_mtime_ns
    assert asyncio.run(handler.daily_summary_catchup()) is None  # ikinci kez uretmez
    assert path.stat().st_mtime_ns == stamp


def test_job_is_registered_and_can_be_disabled(settings):
    handler = SchedulerHandler(settings, broadcaster=NotificationBroadcaster())
    assert handler.summary_at == (23, 30)
    off = SchedulerHandler(settings.model_copy(update={"daily_summary_time": "kapali"}),
                           broadcaster=NotificationBroadcaster())
    assert off.summary_at is None


def test_morning_briefing_gets_yesterdays_open_items(settings, monkeypatch):
    yesterday = (datetime.now() - timedelta(days=1)).date()
    ds.write_summary(settings.obsidian_dir, yesterday,
                     "## Özet\nx\n\n## Yapılanlar\n- y\n\n## Açık kalanlar\n- Rapor gonderilecek\n\n## Notlar\n- yok")
    monkeypatch.setattr("tools.quick_tools.get_weather", lambda _loc: {"error": "yok"})
    handler = SchedulerHandler(settings.model_copy(update={"okul_enabled": False}),
                               broadcaster=NotificationBroadcaster())
    facts = handler.collect_briefing_facts()
    assert facts["dun_kalanlar"] == "- Rapor gonderilecek"
