"""Komuta HUD: kartlar, acilis animasyonu, tam ekran, gorus/konusma kartlari."""
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout

from tests.ui.conftest import FakeWebcam, make_settings, wait_ms


@pytest.fixture()
def hud(qapp):
    from agents.qt_observer import QtOrchestratorObserver
    from ui.hud.hud_window import HudWindow
    from ui.qt_observer import QtEngineObserver

    win = HudWindow(make_settings(), QtEngineObserver(), FakeWebcam(), orch_observer=QtOrchestratorObserver())
    win.resize(1320, 860)
    yield win
    win.hide()
    win.deleteLater()
    qapp.processEvents()


def test_clock_shows_turkish_date(qapp):
    from ui.hud.stat_cards import ClockCard

    card = ClockCard("")
    card.tick(datetime(2026, 9, 25, 20, 46, 7))
    assert card.time_label.text() == "20:46"
    assert card.sec_label.text() == "07"
    assert card.date_label.text() == "25 Eylül 2026 · Cuma"
    assert not card.weather_label.isVisible()      # konum yok -> hava satiri gizli, aga cikilmaz


def test_weather_is_formatted_in_turkish():
    from ui.hud.stat_cards import format_weather

    data = {"konum": "İzmir, Türkiye",
            "simdi": {"sicaklik": 18.4, "durum": "parcali bulutlu"},
            "tahmin": [{"gun": "2026-09-25", "min": 14.2, "max": 24.6, "durum": "acik"}]}
    assert format_weather(data) == "İzmir · 18° parçalı bulutlu  (14°/25°)"
    assert "alınamadı" in format_weather({"error": "timeout"}, "İzmir")


def test_okul_summary_handles_missing_and_real_data():
    from ui.hud.stat_cards import summarize_okul

    assert "bağlı değil" in summarize_okul({"error": "yok"})[0]
    data = {
        "yaklasan_sinavlar": [{"ders": "Matematik I", "kalan_gun": 3}, {"ders": "Fizik", "kalan_gun": 9}],
        "geciken_odevler": [{}], "yakin_odevler": [{}, {}],
        "bugunku_program": [{"baslangic": "09:00"}, {"baslangic": "13:00"}],
    }
    exam, hw, today = summarize_okul(data)
    assert exam == "Matematik I · 3 gün  (+1)"
    assert hw == "1 geciken · 2 bu hafta"
    assert today == "2 ders · ilk 09:00"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API")
def test_system_probe_reads_real_values():
    from ui.hud.stat_cards import SystemProbe

    probe = SystemProbe()
    assert probe.cpu() is None                     # ilk okuma yalnizca taban
    assert 0 <= probe.ram() <= 100
    assert 0 <= probe.disk() <= 100
    second = probe.cpu()
    assert second is None or 0 <= second <= 100


def test_boot_overlay_plays_once_then_greets(qapp, hud):
    hud.show()
    assert hud._boot is not None
    wait_ms(qapp, 2000)
    assert hud._boot is None
    assert "Emrinizdeyim" in hud._caption.text()


def test_f11_toggles_fullscreen_and_chip(qapp, hud):
    hud.show()
    hud._toggle_fullscreen()
    qapp.processEvents()
    assert hud.windowState() & Qt.WindowState.WindowFullScreen
    assert hud._full_btn.isChecked()
    hud._leave_fullscreen()
    qapp.processEvents()
    assert not (hud.windowState() & Qt.WindowState.WindowFullScreen)
    assert not hud._full_btn.isChecked()


def test_vision_card_expands_on_click(qapp, hud):
    assert hud._vision_box.direction() == QBoxLayout.Direction.LeftToRight
    hud._webcam_view.clicked.emit()
    assert hud._vision_box.direction() == QBoxLayout.Direction.TopToBottom
    assert hud._webcam_view.minimumHeight() == 150


def test_talk_drawer_hidden_until_toggled(qapp, hud):
    hud.show()
    assert not hud._talk_card.isVisible()
    hud._talk_btn.setChecked(True)
    assert hud._talk_card.isVisible()


def test_agent_and_task_cards_show_counts(qapp, hud):
    specs = [SimpleNamespace(name=f"a{i}", title=f"Ajan {i}", department=SimpleNamespace(value=d),
                             autonomy=SimpleNamespace(value="fully_autonomous"))
             for i, d in enumerate(["okul", "okul", "bilgi"])]
    hud._on_agents_loaded(specs)
    assert hud._agents_card.meta_label.text() == "2 departman · 3 ajan"
    hud._on_orch_task(SimpleNamespace(id="t1", agent="a0", status="running", result="", detail=""))
    assert hud._tasks_card.meta_label.text().startswith("1/1")


def test_fits_small_laptop_screens(qapp, hud):
    # 1024 px'e kadar kuculebilmeli (1366x768 dizustu + yan yana pencere)
    assert hud.minimumSizeHint().width() <= 1024
    hud.resize(1024, 700)
    hud.show()
    qapp.processEvents()
    assert hud.width() == 1024
    assert not hud._tag.isVisible()


def test_chips_are_text_not_emoji(qapp, hud):
    for btn in (hud._mic_btn, hud._cam_btn, hud._screen_btn, hud._home_btn):
        assert btn.text().isupper() and btn.text().isalpha()


def test_team_chip_toggles_stark_team_window(hud, monkeypatch):
    calls = []

    class FakeTeam:
        open_ = False

        def open(self):
            calls.append("open"); FakeTeam.open_ = True
            return {"status": "acildi", "closable": True}

        def close(self):
            calls.append("close"); FakeTeam.open_ = False
            return {"status": "kapatildi"}

        def is_open(self):
            return FakeTeam.open_

    monkeypatch.setattr("tools.app_launcher.StarkTeamWindow", FakeTeam)
    btn = hud._team_btn
    assert btn.text() == "EKİP" and btn.isCheckable() and btn.parent() is not None
    btn.click()
    assert calls == ["open"] and btn.isChecked()
    btn.click()
    assert calls == ["open", "close"] and not btn.isChecked()

    btn.click()                      # pencere elle kapatildi -> dugme kendiliginden soner
    FakeTeam.open_ = False
    hud._watch_stark_team()
    assert not btn.isChecked()


def test_mini_calendar_marks_today(qapp):
    from datetime import date

    from ui.hud.stat_cards import ClockCard, MiniCalendar

    cal = MiniCalendar()
    cal.set_date(date(2026, 10, 12))            # Pazartesi, ayin 3. haftasi
    assert cal.today_cell() == (2, 0)
    assert cal.weeks[0][:3] == [0, 0, 0] and cal.weeks[0][3] == 1
    card = ClockCard("")
    card.tick(datetime(2026, 9, 25, 20, 46, 7))
    assert card.calendar.today == date(2026, 9, 25)


def test_meter_bar_color_follows_thresholds(qapp):
    from ui import theme
    from ui.hud.stat_cards import MeterBar

    bar = MeterBar("CPU")
    assert bar.bar_color() == theme.ACCENT       # deger yok
    for value, color in ((40, theme.ACCENT), (75, theme.GOLD), (95, theme.BAD)):
        bar.set_value(value)
        assert bar.bar_color() == color


def test_routine_rows_list_reminders_before_routines():
    from ui.hud.stat_cards import routine_rows

    now = datetime(2026, 10, 12, 8, 0)
    routines = [{"name": "Günlük Brifing", "schedule": "her gun 09:00", "enabled": False},
                {"name": "Yedek", "schedule": "haftalik", "enabled": True}]
    reminders = [{"text": "Toplantı", "fire_at": "2026-10-12T14:30:00+03:00"},
                 {"text": "Ödev", "fire_at": "2026-10-15T10:00:00+03:00"}]
    assert routine_rows(routines, reminders, now) == [
        ("14:30", "Toplantı", "BEKLİYOR", True),
        ("15.10", "Ödev", "BEKLİYOR", True),
        ("09:00", "Günlük Brifing", "KAPALI", False),
        ("—", "Yedek", "AÇIK", True),
    ]


def test_routines_card_shows_rows_or_empty_state(qapp):
    from ui.hud.stat_cards import RoutinesCard

    card = RoutinesCard(fetch_fn=lambda: ([{"name": "Brifing", "schedule": "her gun 09:00"}], []))
    assert card.rows == [("09:00", "Brifing", "AÇIK", True)]
    assert card.empty_label.isHidden() and card.meta_label.text() == "1 kayıt"

    def boom():
        raise OSError("dosya yok")

    empty = RoutinesCard(fetch_fn=boom)          # okunamayan veri karti cokertmez
    assert empty.rows == [] and not empty.empty_label.isHidden()


def test_quick_command_tile_sends_to_live_session(qapp, hud):
    from ui.hud.stat_cards import QUICK_COMMANDS

    sent = []
    hud._quick_card.tiles[1].click()             # motor baglanmadan: sessizce yok sayilir
    hud.attach_worker(SimpleNamespace(inject_bridge_message=sent.append))
    before = hud._transcript.bubble_count
    hud._quick_card.tiles[1].click()
    assert sent == [QUICK_COMMANDS[1][1]]
    assert hud._transcript.bubble_count == before + 1


def test_ticker_follows_latest_log_line(qapp, hud):
    hud.show()
    hud._log.add_event("✓", "get_weather -> tamam")
    assert "get_weather" in hud._ticker.text()


def test_agent_detail_opens_on_selection(qapp, hud):
    specs = [SimpleNamespace(name="a0", title="Ajan 0", department=SimpleNamespace(value="okul"),
                             autonomy=SimpleNamespace(value="fully_autonomous"))]
    hud._on_agents_loaded(specs)
    detail = hud._parts["detail"]
    assert detail.isHidden()
    hud._on_agent_selected("dept:okul")
    assert detail.isHidden()
    hud._on_agent_selected("a0")
    assert not detail.isHidden()


def test_task_counter_shows_active_tasks(qapp, hud):
    hud._on_orch_task(SimpleNamespace(id="t1", agent="a0", status="running", result="", detail=""))
    hud._on_orch_task(SimpleNamespace(id="t2", agent="a1", status="done", result="ok", detail=""))
    assert hud._task_count_label.text() == "1"
    assert "2 toplam" in hud._task_sub_label.text()


def test_persona_card_sits_bottom_right_and_switches_via_worker(hud, qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    card = hud._persona_card
    assert card.title_label.text() == "EKİPLER"
    assert list(card.chips) == ["cyraen", "friday", "ultron"]
    card.set_active("cyraen")  # gercek data/persona.json'dan bagimsiz
    hud.show()
    wait_ms(qapp, 50)
    assert card.mapTo(hud, QPoint(0, 0)).x() > hud.width() // 2  # sag sutun

    calls = []
    QTest.mouseClick(card.chips["ultron"], Qt.MouseButton.LeftButton)  # worker yok: cokmez
    hud._worker = SimpleNamespace(set_persona=calls.append)
    QTest.mouseClick(card.chips["ultron"], Qt.MouseButton.LeftButton)
    assert calls == ["ultron"]
    assert card.active == "cyraen"  # motor onaylayana kadar degismez

    hud._observer.persona.emit("ultron")
    wait_ms(qapp, 20)
    assert card.active == "ultron" and card.meta_label.text() == "ULTRON"
    assert card.chips["ultron"].active and not card.chips["cyraen"].active
    QTest.mouseClick(card.chips["ultron"], Qt.MouseButton.LeftButton)  # zaten aktif
    assert calls == ["ultron"]
    hud._worker = None


def test_palettes_recolor_everything_and_drop_the_old_orange():
    from ui import theme

    seen = set()
    for key in ("cyraen", "friday", "ultron"):
        assert theme.apply_palette(key) == key
        assert "rgba(255, 109, 0" not in theme.QSS and "#ff8c42" not in theme.QSS
        assert theme.ACCENT in theme.QSS and theme.HUD_TICK == theme.SPEAK == theme.ACCENT
        assert theme.DEPT_COLORS[0] == theme.ACCENT
        seen.add(theme.ACCENT)
    assert len(seen) == 3
    assert theme.apply_palette("yok") == "cyraen"


def test_persona_switch_rethemes_the_whole_hud(hud, qapp):
    from ui import theme
    hud.show()
    wait_ms(qapp, 30)
    assert hud._brand.text() == "CYRAEN_OS" and theme.PERSONA == "cyraen"
    assert not hud._fx_overlay.isVisible() and not hud._fx_overlay.timer_running
    hud._caption.setText(theme.branding()["greeting"])

    hud._observer.persona.emit("ultron")
    wait_ms(qapp, 30)
    assert hud._brand.text() == "ULTRON_OS"
    assert hud._tag.text() == "BAĞIMSIZ ZEKÂ"
    assert "ULTRON" in hud._bridge_input.placeholderText()
    assert hud._caption.text() == theme.BRANDING["ultron"]["greeting"]   # karsilama da degisti
    assert hud.windowTitle() == "ULTRON"
    assert hud._clock_card._tick.name() == theme.ACCENT.lower() == "#ff4d4d"
    assert qapp.styleSheet() == theme.QSS
    assert hud._fx_overlay.isVisible() and hud._fx_overlay.timer_running

    hud._fx_overlay._start_glitch()          # glitch: logo kayar, sonra geri doner
    assert hud._fx_overlay.glitch_active and hud._brand.contentsMargins().left() > 0
    hud._fx_overlay._stop_glitch()
    assert hud._brand.contentsMargins().left() == 0 and hud._fx_overlay.timer_running

    hud._observer.persona.emit("friday")
    wait_ms(qapp, 30)
    assert hud._brand.text() == "FRIDAY_OS" and theme.EFFECT == "friday"
    assert not hud._fx_overlay.isVisible() and not hud._fx_overlay.timer_running

    hud._observer.persona.emit("cyraen")
    wait_ms(qapp, 30)
    assert hud._brand.text() == "CYRAEN_OS" and hud._caption.text() == theme.BRANDING["cyraen"]["greeting"]


def test_transcript_uses_the_active_persona_name(qapp):
    from ui import theme
    from ui.widgets.transcript_view import TranscriptView

    view = TranscriptView()
    theme.apply_palette("friday")
    view.add_assistant("Hallettim.")
    assert "FRIDAY" in view.toPlainText()
