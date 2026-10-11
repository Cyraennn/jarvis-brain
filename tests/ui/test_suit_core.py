"""HUD merkezi (zirh bustu + arc reactor + departman kadrani)."""
from types import SimpleNamespace

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from tests.ui.conftest import wait_ms


def _specs():
    rows = [("s1", "sistem"), ("s2", "sistem"), ("o1", "okul"), ("b1", "bilgi"), ("g1", "gunluk")]
    return [SimpleNamespace(name=n, title=n.upper(), department=SimpleNamespace(value=d),
                            autonomy=SimpleNamespace(value="fully_autonomous")) for n, d in rows]


def _core(qapp):
    from ui.hud.suit_core import SuitCore

    core = SuitCore()
    core.resize(700, 600)
    core.set_agents(_specs())
    core.show()
    wait_ms(qapp, 80)
    return core


def test_active_tasks_light_their_department(qapp):
    core = _core(qapp)
    core.set_agent_status("s1", "running")
    core.set_agent_status("s2", "queued")
    assert core.active_count("sistem") == 2
    core.set_agent_status("s1", "done")
    assert core.active_count("sistem") == 1
    core.set_agent_status("bilinmeyen", "running")      # cokmemeli
    assert core.active_count("okul") == 0


def test_dial_label_click_emits_department(qapp):
    core = _core(qapp)
    core.repaint()
    assert set(core._label_rects) == {"bilgi", "gunluk", "okul", "sistem"}
    got = []
    core.node_clicked.connect(got.append)
    rect = core._label_rects["okul"]
    QTest.mouseClick(core, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert got == ["dept:okul"]
    assert core._selected == "okul"


def test_dial_labels_never_overlap_on_small_widget(qapp):
    core = _core(qapp)
    core.resize(400, 420)
    core.repaint()
    rects = sorted(core._label_rects.values(), key=lambda r: r.top())
    for a, b in zip(rects, rects[1:]):
        assert a.bottom() <= b.top() + 0.5
    assert all(r.right() <= core.width() for r in rects)


def test_power_line_follows_voice_level(qapp):
    core = _core(qapp)
    assert core.power_text() == "Güç seviyesi şu an %0 ve sabit seyrediyor."
    core.set_center_mode("speaking")
    core.set_center_level(0.8)
    wait_ms(qapp, 400)
    text = core.power_text()
    assert "%0 " not in text and "yükseliyor" in text


def test_static_layer_cached_per_size(qapp):
    core = _core(qapp)
    core.repaint()
    first = core.static_renders
    for _ in range(3):
        core.repaint()
    assert core.static_renders == first
    core.resize(640, 560)
    core.repaint()
    assert core.static_renders == first + 1


def test_hud_uses_suit_core_and_classic_keeps_graph(qapp, main_window):
    from ui.hud.suit_core import SuitCore
    from ui.widgets.brain_graph import BrainGraph

    expected = SuitCore if type(main_window).__name__ == "HudWindow" else BrainGraph
    assert isinstance(main_window._graph, expected)
    assert QPointF  # isim kullanimi (ruff F401)
