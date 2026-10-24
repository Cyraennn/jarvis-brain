"""HUD merkezi (donen 3B yorunge: parcacik kuresi + departman halkasi + ajan rozet halkasi)."""
import math
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.ui.conftest import wait_ms


def _specs():
    rows = [("s1", "sistem"), ("s2", "sistem"), ("o1", "okul"), ("b1", "bilgi"), ("g1", "gunluk")]
    return [SimpleNamespace(name=n, title=n.upper(), department=SimpleNamespace(value=d),
                            autonomy=SimpleNamespace(value="fully_autonomous")) for n, d in rows]


def _graph(qapp):
    from ui.hud.command_graph import CommandGraph

    g = CommandGraph()
    g.resize(700, 600)
    g.set_agents(_specs())
    g.show()
    wait_ms(qapp, 80)
    g.repaint()
    return g


def test_orbit_is_projected_with_perspective(qapp):
    g = _graph(qapp)
    inner, outer, _core = g._rings
    front, front_scale, front_depth = g._project(math.pi / 2, outer)     # izleyiciye en yakin nokta
    back, back_scale, back_depth = g._project(-math.pi / 2, outer)
    side, side_scale, side_depth = g._project(0.0, outer)
    assert (front_depth, back_depth) == (1.0, -1.0) and abs(side_depth) < 1e-9
    assert front_scale > side_scale == 1.0 > back_scale                  # ondeki buyuk, arkadaki kucuk
    assert front.y() > g._center.y() > back.y()                          # on asagida, arka yukarida
    assert front.y() - back.y() < 2 * outer * 0.75                       # duzlem yatik: dikey eksen basik
    assert math.isclose(side.x() - g._center.x(), outer)
    assert 0 <= back.y() and front.y() <= g.height()                     # tuvale sigar


def test_all_agents_are_visible_and_depth_sorted(qapp):
    g = _graph(qapp)
    agents = [ag for nodes in g._agents.values() for ag in nodes]
    assert len(agents) == 5
    assert len({(round(a.pos.x()), round(a.pos.y())) for a in agents}) == 5   # ust uste binmez
    assert all(g.rect().contains(a.pos.toPoint()) for a in agents)
    nearest, farthest = max(agents, key=lambda a: a.depth), min(agents, key=lambda a: a.depth)
    assert nearest.scale > farthest.scale and nearest.pos.y() > farthest.pos.y()
    assert g._fade(nearest.depth) > g._fade(farthest.depth)


def test_orbit_spins_on_its_own_and_follows_drag(qapp):
    g = _graph(qapp)
    start = g._rot
    wait_ms(qapp, 300)
    assert g._rot > start                                                # otomatik donus
    agent = g._agents["okul"][0]
    got = []
    g.node_clicked.connect(got.append)
    before = g._rot
    QTest.mousePress(g, Qt.MouseButton.LeftButton, pos=agent.pos.toPoint())
    QTest.mouseMove(g, agent.pos.toPoint() + QPoint(60, 0))
    QTest.mouseMove(g, agent.pos.toPoint() + QPoint(120, 0))
    assert g._dragging and g._rot < before - 0.5                         # suruklerken elle doner
    frozen = g._rot
    wait_ms(qapp, 150)
    assert g._rot == frozen                                              # suruklerken otomatik donus durur
    QTest.mouseRelease(g, Qt.MouseButton.LeftButton, pos=agent.pos.toPoint() + QPoint(120, 0))
    assert got == [] and not g._dragging                                 # surukleme tiklama sayilmaz


def test_each_department_gets_its_own_color(qapp):
    g = _graph(qapp)
    colors = {g._dept_color[d.key].name() for d in g._departments}
    assert len(colors) == 4
    agent = g._agents["sistem"][0]
    assert g._color_of(agent) == g._dept_color["sistem"]


def test_clicks_tell_agents_and_departments_apart(qapp):
    g = _graph(qapp)
    got = []
    g.node_clicked.connect(got.append)
    agent = g._agents["okul"][0]
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=agent.pos.toPoint())
    dept = next(d for d in g._departments if d.key == "sistem")
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=dept.pos.toPoint())
    assert got == ["o1", "dept:sistem"]
    assert g._expanded == "sistem"
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=g.rect().topLeft())   # bosluk: secim kalkar
    assert g._expanded is None


def test_running_task_lights_agent_and_department(qapp):
    g = _graph(qapp)
    g.set_agent_status("s1", "running")
    agent = g._agents["sistem"][0]
    dept = next(d for d in g._departments if d.key == "sistem")
    assert agent.target == 1.0 and dept.target == 1.0
    g.set_agent_status("s1", "done")
    assert agent.target == 0.0 and agent.flash == 1.0
    g.set_agent_status("bilinmeyen", "running")      # cokmemeli


def test_idle_and_busy_frame_rates(qapp):
    from ui.hud.command_graph import CommandGraph

    g = _graph(qapp)
    wait_ms(qapp, 200)
    assert g._timer.interval() == CommandGraph.IDLE_MS
    g.set_center_mode("speaking")
    g.set_center_level(0.8)
    wait_ms(qapp, 200)
    assert g._timer.interval() == CommandGraph.BUSY_MS


def test_static_layer_cached_per_size(qapp):
    g = _graph(qapp)
    first = g.static_renders
    for _ in range(3):
        g.repaint()
    assert g.static_renders == first
    g.resize(640, 560)
    g.repaint()
    assert g.static_renders == first + 1


def test_hud_uses_command_graph_and_classic_keeps_brain_graph(qapp, main_window):
    from ui.hud.command_graph import CommandGraph
    from ui.widgets.brain_graph import BrainGraph

    if type(main_window).__name__ == "HudWindow":
        assert isinstance(main_window._graph, CommandGraph)
    else:
        assert type(main_window._graph) is BrainGraph
