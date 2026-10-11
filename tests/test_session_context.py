"""Kesintisiz hafiza: temiz oturum baglami + oturum devam tutamagi."""

from __future__ import annotations

import time
from datetime import date, datetime
from types import SimpleNamespace

from core import brain_engine
from core.brain_engine import BrainEngine
from core.daily_summary import write_summary
from core.session_context import build_context, conversation_tail, now_line

NOW = datetime(2026, 10, 11, 15, 20)


def _vault(tmp_path, turns: list[str]):
    conv = tmp_path / "Konusmalar"
    conv.mkdir()
    body = "---\ntags: [jarvis]\n---\n\n# Konusma - 11.10.2026\n\n" + "\n\n".join(turns) + "\n"
    (conv / "2026-10-11.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_now_line_has_date_weekday_and_time():
    line = now_line(NOW)
    assert "11.10.2026 Pazar" in line and "15:20" in line and "get_current_datetime" in line


def test_context_without_vault_is_just_the_date():
    text = build_context(SimpleNamespace(obsidian_dir=None), NOW)
    assert "11.10.2026" in text and "BUGUN DAHA ONCE" not in text and "ARKA PLAN" not in text


def test_context_includes_todays_tail_and_yesterdays_summary(tmp_path):
    base = _vault(tmp_path, ["**14:01 · Sen:** Yarinki sinav kacta?",
                             "**14:02 · JARVIS:** Saat 10:00'da, efendim."])
    write_summary(base, date(2026, 10, 10),
                  "## Özet\nOdev bitirildi.\n\n## Yapılanlar\n- odev\n\n"
                  "## Açık kalanlar\n- Rapor gonderilecek\n\n## Notlar\n- yok")
    text = build_context(SimpleNamespace(obsidian_dir=base), NOW)
    assert "Yarinki sinav kacta?" in text and "Saat 10:00'da" in text
    assert "DUNUN OZETI (10.10.2026)" in text and "Rapor gonderilecek" in text
    assert "Yapılanlar" not in text  # yalniz Ozet + Acik kalanlar tasinir
    assert "ARKA PLAN" in text


def test_tail_keeps_newest_turns_and_trims_long_agent_output(tmp_path):
    turns = [f"**10:{i:02d} · Sen:** soru {i}" for i in range(40)]
    turns.append("**11:00 · Ajan:** " + "x" * 900)
    base = _vault(tmp_path, turns)
    tail = conversation_tail(base / "Konusmalar" / "2026-10-11.md", max_lines=5)
    assert len(tail) == 5 and tail[0].endswith("soru 36") and tail[-1].endswith(" ...")
    assert len(tail[-1]) < 240
    small = conversation_tail(base / "Konusmalar" / "2026-10-11.md", max_lines=30, max_chars=260)
    assert len(small) == 2 and small[0].endswith("soru 39")  # butce dolunca en yeniler kalir
    assert sum(map(len, small)) <= 260
    assert conversation_tail(tmp_path / "yok.md") == []


# ------------------------------------------------------------------ devam tutamagi

def _engine(tmp_path=None) -> BrainEngine:
    eng = BrainEngine.__new__(BrainEngine)
    eng.settings = SimpleNamespace(
        session_context_enabled=True, obsidian_dir=None, voice_name="Puck",
        load_system_prompt=lambda: "TEMEL ISTEM",
    )
    eng._resume_handle = None
    eng._resume_saved_at = 0.0
    eng._resume_failures = 0
    eng._attempt_active = False
    eng._proactive_audio = False
    eng._connect_started = time.monotonic()
    return eng


def _prompt(cfg) -> str:
    return cfg.system_instruction.parts[0].text


def test_fresh_session_gets_context_and_asks_for_resumption_handles(monkeypatch):
    monkeypatch.setattr(brain_engine, "get_tools", lambda: [])
    cfg = _engine()._build_config()
    assert _prompt(cfg).startswith("TEMEL ISTEM") and "OTURUM BAGLAMI" in _prompt(cfg)
    assert cfg.session_resumption is not None and cfg.session_resumption.handle is None


def test_resumed_session_sends_handle_and_no_stale_context(monkeypatch):
    monkeypatch.setattr(brain_engine, "get_tools", lambda: [])
    eng = _engine()
    eng._on_resumption_update(SimpleNamespace(resumable=True, new_handle="h-1"))
    cfg = eng._build_config()
    assert cfg.session_resumption.handle == "h-1"
    assert _prompt(cfg) == "TEMEL ISTEM"  # model zaten hatirliyor


def test_non_resumable_update_keeps_the_last_good_handle():
    eng = _engine()
    eng._on_resumption_update(SimpleNamespace(resumable=True, new_handle="h-1"))
    eng._on_resumption_update(SimpleNamespace(resumable=False, new_handle=None))
    assert eng._resume_handle == "h-1"


def test_handle_survives_offline_failures_but_not_server_rejection():
    eng = _engine()
    eng._on_resumption_update(SimpleNamespace(resumable=True, new_handle="h-1"))
    for _ in range(5):  # internet yok: baglanamamak tutamagi harcamaz
        eng._note_resume_outcome(failed_before_active=True, online=False)
    assert eng._resume_handle == "h-1"
    eng._note_resume_outcome(failed_before_active=False, online=True)  # oturum ortasi kopus
    assert eng._resume_handle == "h-1"
    eng._note_resume_outcome(failed_before_active=True, online=True)
    assert eng._resume_handle == "h-1"  # tek hata gecici olabilir
    eng._note_resume_outcome(failed_before_active=True, online=True)
    assert eng._resume_handle is None  # iki kez reddedildi: temiz oturum


def test_setup_rejection_blames_the_handle_before_proactive_audio():
    eng = _engine()
    eng._proactive_audio = True
    eng._resume_handle = "h-1"
    eng._check_setup_rejection(RuntimeError("1007 invalid argument"))
    assert eng._proactive_audio  # once tutamak elenir
    eng._resume_handle = None
    eng._check_setup_rejection(RuntimeError("1007 invalid argument"))
    assert not eng._proactive_audio
