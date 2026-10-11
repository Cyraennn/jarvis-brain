"""Sinematik HUD: kartlar, acilis animasyonu, tam ekran, gorus/konusma kartlari."""
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
