"""Asama 1: performans ve dogruluk duzeltmeleri."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage


def jpeg_bytes(color="#345678", size=(64, 48)) -> bytes:
    img = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG")
    return bytes(ba)


# ------------------------------------------------------------------ WebcamView
def test_webcam_same_frame_is_decoded_and_scaled_once(qapp):
    from ui.widgets.webcam_view import WebcamView

    frame = jpeg_bytes()
    view = WebcamView(lambda: frame)
    view.resize(300, 180)
    view.show()
    for _ in range(100):
        view._poll()
    view.grab()
    view.grab()
    assert view.decode_count == 1
    assert view.scale_count == 1          # olcekleme onbellekten, her boyamada yeniden degil
    view.hide()


def test_webcam_new_frame_and_resize_invalidate_cache(qapp):
    from ui.widgets.webcam_view import WebcamView

    holder = {"f": jpeg_bytes("#111111")}
    view = WebcamView(lambda: holder["f"])
    view.resize(300, 180)
    view.show()
    view._poll()
    view.grab()
    holder["f"] = jpeg_bytes("#eeeeee")
    view._poll()
    view.grab()
    assert view.decode_count == 2 and view.scale_count == 2
    view.resize(400, 240)
    view.grab()
    assert view.scale_count == 3
    view.hide()


def test_webcam_hidden_stops_timer(qapp):
    from ui.widgets.webcam_view import WebcamView

    view = WebcamView(lambda: None)
    view.show()
    assert view._timer.isActive()
    view.hide()
    assert not view._timer.isActive()
    view.show()
    assert view._timer.isActive()
    view.hide()


# ------------------------------------------------------------------ TranscriptView
def test_transcript_is_bounded(qapp):
    from ui.widgets import transcript_view as tv

    view = tv.TranscriptView()
    view.resize(400, 300)
    for i in range(1000):
        view.add_user(f"mesaj {i}")
    assert view.bubble_count <= tv.MAX_BUBBLES + tv._TRIM_SLACK
    text = view.toPlainText()
    assert "mesaj 999" in text
    assert "mesaj 0\n" not in text        # en eski atildi


def test_transcript_does_not_force_scroll_when_user_scrolled_up(qapp):
    from ui.widgets.transcript_view import TranscriptView

    view = TranscriptView()
    view.resize(400, 200)
    view.show()
    for i in range(60):
        view.add_assistant(f"satir {i} " * 8)
    qapp.processEvents()
    bar = view.verticalScrollBar()
    bar.setValue(0)
    view.add_user("yeni mesaj")
    qapp.processEvents()
    assert bar.value() == 0               # kullanici yukaridaydi: zorla asagi cekilmedi
    view.hide()


# ------------------------------------------------------------------ LogView
def test_log_lines_are_batched_and_bounded(qapp):
    from ui.widgets.log_view import LogView, _MAX_BLOCKS

    view = LogView()
    for i in range(5000):
        view.add_log("INFO", f"satir {i}")
    assert view.blockCount() <= 1          # henuz eklenmedi: kuyrukta
    while view._pending:
        view.flush()
    assert view.blockCount() <= _MAX_BLOCKS
    assert "satir 4999" in view.toPlainText()


def test_log_keeps_scroll_position_when_user_scrolled_up(qapp):
    from ui.widgets.log_view import LogView

    view = LogView()
    view.resize(300, 120)
    view.show()
    for i in range(200):
        view.add_log("INFO", f"eski {i}")
    while view._pending:
        view.flush()
    qapp.processEvents()
    bar = view.verticalScrollBar()
    bar.setValue(0)
    view.add_log("INFO", "yeni")
    view.flush()
    assert bar.value() == 0
    view.hide()


# ------------------------------------------------------------------ BrainGraph
def test_graph_static_layer_rendered_once_per_size(qapp):
    from ui.widgets.brain_graph import BrainGraph

    g = BrainGraph()
    g.resize(500, 500)
    g.show()
    for _ in range(5):
        g.grab()
    assert g.static_renders == 1
    g.resize(620, 560)
    g.grab()
    assert g.static_renders == 2
    g.hide()


def test_graph_timer_stops_when_hidden_or_inactive(qapp):
    from ui.widgets.brain_graph import BrainGraph

    g = BrainGraph()
    g.show()
    assert g._timer.isActive()
    g.hide()
    assert not g._timer.isActive()
    g.show()
    assert g._timer.isActive()
    g.set_active(False)                   # pencere kucultuldu
    assert not g._timer.isActive()
    g.set_active(True)
    assert g._timer.isActive()
    g.hide()


def test_graph_idle_uses_lower_fps_and_busy_uses_higher(qapp):
    from ui.widgets.brain_graph import BrainGraph

    g = BrainGraph()
    g.show()
    for _ in range(3):
        g._tick()
    assert g._timer.interval() == BrainGraph.IDLE_MS
    g.set_center_mode("listening")
    g._tick()
    assert g._timer.interval() == BrainGraph.BUSY_MS
    g.hide()


def test_graph_animation_speed_is_independent_of_fps(qapp, monkeypatch):
    """Ayni gercek sure gecince _t ayni ilerlemeli (15 FPS'te animasyon yavaslamamali)."""
    from ui.widgets import brain_graph as bg

    clock = {"now": 1000.0}
    monkeypatch.setattr(bg.time, "monotonic", lambda: clock["now"])
    fast, slow = bg.BrainGraph(), bg.BrainGraph()
    fast._last_tick = clock["now"]
    for _ in range(30):                   # 30 x 33 ms = ~1 sn
        clock["now"] += 0.033
        fast._tick()
    clock["now"] = 1000.0
    slow._last_tick = clock["now"]
    for _ in range(15):                   # 15 x 66 ms = ~1 sn
        clock["now"] += 0.066
        slow._tick()
    assert fast._t == pytest.approx(slow._t, rel=0.02)


# ------------------------------------------------------------------ MainWindow
def test_status_bar_shows_real_model_and_turkish_text(qapp, main_window):
    main_window.show()
    assert "native-audio" in main_window._sb_model.text()
    assert "models/" not in main_window._sb_model.text()
    assert main_window._sb_tasks.text() == "GÖREV 0/0"
    main_window._observer.connection.emit("closed")
    qapp.processEvents()
    assert "BAĞLANTI YOK" in main_window._conn_pill.text()


def test_task_counter_tracks_active_over_total(qapp, main_window):
    def upd(i, status):
        return SimpleNamespace(id=i, agent="kod_denetcisi", status=status, result="", detail="")

    w = main_window
    w._on_orch_task(upd("t1", "queued"))
    w._on_orch_task(upd("t2", "queued"))
    assert w._sb_tasks.text() == "GÖREV 2/2"
    w._on_orch_task(upd("t1", "running"))
    w._on_orch_task(upd("t1", "done"))
    assert w._sb_tasks.text() == "GÖREV 1/2"        # biten artik aktif sayilmaz
    w._on_orch_task(upd("t2", "failed"))
    assert w._sb_tasks.text() == "GÖREV 0/2"


def test_focus_mode_hides_and_restores_side_panels(qapp, main_window):
    w = main_window
    w.show()
    w._right_btn.setChecked(False)                  # kullanici sagi zaten kapatmis
    w._home_btn.setChecked(True)
    assert not w._left_sidebar.isVisible() and not w._right_sidebar.isVisible()
    w._home_btn.setChecked(False)
    assert w._left_sidebar.isVisible()              # eskiden acikti: geri geldi
    assert not w._right_sidebar.isVisible()         # eskiden kapaliydi: kapali kaldi


def test_minimize_stops_graph_animation(qapp, main_window):
    from PySide6.QtCore import QEvent

    w = main_window
    w.show()
    assert w._graph._timer.isActive()
    w.showMinimized()
    w.changeEvent(QEvent(QEvent.Type.WindowStateChange))
    qapp.processEvents()
    assert not w._graph._timer.isActive()
    w.showNormal()
    w.changeEvent(QEvent(QEvent.Type.WindowStateChange))
    qapp.processEvents()
    assert w._graph._timer.isActive()


def test_no_ascii_turkish_leftovers_in_visible_labels(qapp, main_window):
    from PySide6.QtWidgets import QLabel, QPushButton

    bad = ("BAGLAN", "KONUSMA", "GONDER", "GORUS", "GUNLUGU", "Cikis")
    widgets = main_window.findChildren(QLabel) + main_window.findChildren(QPushButton)
    assert widgets
    for widget in widgets:
        text = widget.text()
        assert not any(b in text for b in bad), text


def test_turkish_lower_handles_dotted_and_dotless_i():
    from ui.main_window import _tr_lower

    assert _tr_lower("BAĞLI") == "bağlı"
    assert _tr_lower("YENİDEN BAĞLANIYOR") == "yeniden bağlanıyor"
    assert _tr_lower("BAĞLANTI YOK") == "bağlantı yok"


def test_turkish_upper_and_department_titles():
    from ui.strings import DEPARTMENT_TITLES, tr_upper

    assert tr_upper("İletişim") == "İLETİŞİM"
    assert tr_upper("ılık") == "ILIK"
    assert all(v == v.strip() and v for v in DEPARTMENT_TITLES.values())
    assert set(DEPARTMENT_TITLES) == {"okul", "iletisim", "sistem", "telefon", "bilgi", "gunluk"}
