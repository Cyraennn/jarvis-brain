"""Arayuz analizi duzeltmeleri: onay zaman asimi, IO durumu, odak/departman senkronu, yelpaze."""
import math
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QTimer

from tests.ui.conftest import wait_ms


def _log_text(win) -> str:
    win._log.flush()
    return win._log.toPlainText()


def _specs(dept: str, n: int) -> list:
    return [
        SimpleNamespace(name=f"{dept}_{i}", title=f"{dept.title()} Ajanı Uzun Başlık {i}",
                        department=SimpleNamespace(value=dept),
                        autonomy=SimpleNamespace(value="fully_autonomous"))
        for i in range(n)
    ]


# ------------------------------------------------------------------ onay
def test_confirm_dialog_closes_itself_when_request_expires(qapp, main_window):
    from ui.qt_observer import ConfirmRequest

    w = main_window
    w.show()
    req = ConfirmRequest("Not Defteri kapatılsın mı?")
    QTimer.singleShot(200, lambda: setattr(req, "expired", True))
    w._on_confirm_requested(req)          # exec() doner cunku diyalog kendini kapatir
    assert w._active_dialog is None
    assert not req.wait(0)                # sonuc motora hic iletilmedi
    assert "zaman aşımına" in _log_text(w)
    assert "Onay verildi" not in _log_text(w)


def test_confirm_dialog_yes_resolves_request(qapp, main_window):
    from ui.qt_observer import ConfirmRequest

    w = main_window
    w.show()
    req = ConfirmRequest("Emin misin?")
    QTimer.singleShot(150, lambda: w._active_dialog.defaultButton().click())
    w._on_confirm_requested(req)
    assert req.wait(0) and req.result is True
    assert "Onay verildi" in _log_text(w)


def test_confirm_brings_hidden_window_forward_then_rehides(qapp, main_window):
    from agents.qt_observer import ApprovalRequest

    w = main_window
    w.hide()
    req = ApprovalRequest("Ajan çalışsın mı?")
    seen = {}

    def answer():
        seen["visible"] = w.isVisible()
        w._active_dialog.defaultButton().click()

    QTimer.singleShot(150, answer)
    w._on_approval_requested(req)
    assert seen["visible"] is True
    assert req.result is True
    assert not w.isVisible() or w._tray is None


# ------------------------------------------------------------- durum cubugu
def test_io_status_reflects_settings_at_startup(qapp, main_window):
    assert "cam ○" in main_window._sb_io.text()     # conftest: webcam_enabled=False


def test_no_audio_unchecks_mic_and_active_restores(qapp, main_window):
    w = main_window
    assert w._mic_btn.isChecked()
    w._observer.connection.emit("no-audio")
    qapp.processEvents()
    assert not w._mic_btn.isChecked()
    assert "mic ○" in w._sb_io.text()
    w._observer.connection.emit("active")
    qapp.processEvents()
    assert w._mic_btn.isChecked()
    assert "mic ●" in w._sb_io.text()


def test_user_muted_mic_is_not_reenabled_by_reconnect(qapp, main_window):
    w = main_window
    w._mic_btn.setChecked(False)
    w._observer.connection.emit("no-audio")
    w._observer.connection.emit("active")
    qapp.processEvents()
    assert not w._mic_btn.isChecked()


def test_web_url_has_its_own_status_item(qapp, main_window):
    w = main_window
    w.show()
    assert not w._sb_web.isVisible()
    w.attach_web_worker(SimpleNamespace(url="http://192.168.1.5:8770/?key=x"))
    wait_ms(qapp, 1700)
    assert w._sb_web.isVisible()
    assert "8770" in w._sb_web.toolTip()
    assert w._sb_tasks.toolTip() == "Aktif / toplam ajan görevi"


# ------------------------------------------------------------ odak / senkron
def test_opening_a_panel_leaves_focus_mode(qapp, main_window):
    w = main_window
    w.show()
    w._home_btn.setChecked(True)
    w._left_btn.setChecked(True)
    assert not w._home_btn.isChecked()
    assert w._left_sidebar.isVisible()


def test_department_click_expands_tree(qapp, main_window):
    w = main_window
    w._on_agents_loaded(_specs("sistem", 3) + _specs("okul", 2))
    w._on_agent_selected("dept:sistem")
    tree = w._agent_panel._tree
    tops = {tree.topLevelItem(i).text(0): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
    assert tops["▸ SİSTEM"].isExpanded()
    assert not tops["▸ OKUL"].isExpanded()


# ------------------------------------------------------------------ yelpaze
def test_agent_fan_keeps_labels_apart(qapp):
    from ui.widgets.brain_graph import BrainGraph

    g = BrainGraph()
    g.resize(620, 520)
    g.set_agents(_specs("sistem", 7) + _specs("okul", 3))
    g.expand("sistem")
    g._geometry()
    ags = g._agents["sistem"]
    gaps = [math.hypot(a.pos.x() - b.pos.x(), a.pos.y() - b.pos.y()) for a, b in zip(ags, ags[1:])]
    assert min(gaps) >= g._label_w                 # etiketler ust uste binmez


def test_hit_test_picks_nearest_node(qapp):
    from ui.widgets.brain_graph import BrainGraph

    g = BrainGraph()
    g.resize(620, 520)
    g.set_agents(_specs("sistem", 7))
    g.expand("sistem")
    g._geometry()
    target = g._agents["sistem"][3]
    near = QPointF(target.pos.x() + 5, target.pos.y() - 4)
    assert g._hit(near) is target
    assert g._hit(QPointF(-100, -100)) is None
