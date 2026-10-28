"""Holografik beyin haritasi - JARVIS cekirdegi + 6 departman + alt ajanlar.

Merkezde JARVIS arc-reactor. Cevresinde 6 departman dugumu (hex). Bir departmana
tiklaninca alt ajanlari o dugumun etrafinda dairesel acilir. Gorev akisinca kenarlar
parlar, parcaciklar akar.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QToolTip, QWidget

from ui import theme
from ui.strings import DEPARTMENT_TITLES, tr_upper

# Kisilik paleti degisince yerinde guncellenir (command_graph ayni sozlugu kullanir).
_MODE_COLOR: dict[str, QColor] = {}
_ACTIVE = {"queued", "routing", "running", "tool", "awaiting_approval"}
_AUTONOMY_COLOR: dict[str, QColor] = {}


def refresh_palette_colors() -> None:
    _MODE_COLOR.update({
        "idle": QColor(theme.ACCENT_DIM),
        "listening": QColor(theme.ACCENT),
        "speaking": QColor(theme.GOLD),
    })
    _AUTONOMY_COLOR.update({
        "fully_autonomous": QColor(theme.ACCENT),
        "human_assisted": QColor(theme.GOLD),
        "human_led": QColor(theme.MYSTIC),
    })


refresh_palette_colors()


def _rgba(c: QColor, a: int) -> QColor:
    return QColor(c.red(), c.green(), c.blue(), max(0, min(255, a)))


@dataclass
class _Node:
    key: str
    title: str
    kind: str                       # "department" | "agent"
    parent: str = ""
    angle: float = 0.0
    autonomy: str = ""
    activity: float = 0.0
    target: float = 0.0
    flash: float = 0.0
    flash_color: QColor = field(default_factory=lambda: QColor(theme.GOOD))
    pos: QPointF = field(default_factory=QPointF)
    slot: float = 0.0               # ajan: yelpazedeki sira (merkeze gore -k..+k)


class BrainGraph(QWidget):
    BUSY_MS = 33     # ~30 FPS (konusma/dinleme/gorev varken)
    IDLE_MS = 66     # ~15 FPS (bosta)
    DEPT_R = 24.0
    AGENT_R = 15.0
    AGENT_GAP_PX = 104.0   # yelpazede komsu ajanlar arasi hedef yay uzunlugu (etiket cakismasin)
    FAN_MAX_RAD = 3.6      # yelpazenin toplam acisi en fazla (~206 derece)
    node_clicked = Signal(str)       # agent adi veya "dept:<key>"
    agent_clicked = Signal(str)      # geriye uyumluluk (ajan adi)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)

        self._departments: list[_Node] = []
        self._agents: dict[str, list[_Node]] = {}   # dept key -> agents
        self._expanded: str | None = None
        self._label_w = 116            # ajan etiketi genisligi (yelpaze sikistikca daralir)
        self._mode = "idle"
        self._target_level = 0.0
        self._level = 0.0
        self._t = 0.0

        # Paint sirasinda string'den QColor uretmemek icin bir kez hazirlanan renkler
        self._k = self._palette()
        # Statik katman (izgara/halkalar/kose isaretleri) boyut degismedikce bir kez cizilir
        self._static: QPixmap | None = None
        self._static_key: tuple | None = None
        self.static_renders = 0       # gozlem/test

        # Animasyon: mesgulken ~30 FPS, bostayken ~15 FPS, gorunmezken/kucukken durur
        self._active = True
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self.BUSY_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @staticmethod
    def _palette() -> SimpleNamespace:
        return SimpleNamespace(
            **{name: QColor(getattr(theme, name)) for name in (
                "GRID", "ACCENT", "ACCENT_DIM", "BORDER_LIGHT", "MYSTIC", "TEXT", "TEXT_DIM", "BG_CARD",
            )},
            WHITE=QColor("#ffffff"),
        )

    # ------------------------------------------------------------------ API
    def refresh_theme(self) -> None:
        """Kisilik paleti degisti: hazir renkleri ve statik katmani yeniden kur."""
        refresh_palette_colors()
        self._k = self._palette()
        self._static = None
        self.update()

    def set_agents(self, agents: list) -> None:
        """AgentSpec listesi (department + autonomy alanlariyla)."""
        by_dept: dict[str, list] = {}
        for spec in agents:
            dep = getattr(getattr(spec, "department", None), "value", None) or "genel"
            by_dept.setdefault(dep, []).append(spec)

        self._departments = []
        self._agents = {}
        keys = sorted(by_dept)
        n = max(1, len(keys))
        for i, dep in enumerate(keys):
            ang = -math.pi / 2 + (i / n) * math.tau
            self._departments.append(_Node(key=dep, title=_DEP_TITLE.get(dep, dep.title()),
                                           kind="department", angle=ang))
            specs = by_dept[dep]
            m = max(1, len(specs))
            self._agents[dep] = [
                _Node(
                    key=getattr(s, "name", str(s)),
                    title=getattr(s, "title", getattr(s, "name", "?")),
                    kind="agent", parent=dep,
                    angle=ang + (j - (m - 1) / 2) * 0.42,
                    slot=j - (m - 1) / 2,
                    autonomy=getattr(getattr(s, "autonomy", None), "value", ""),
                )
                for j, s in enumerate(specs)
            ]
        self.update()

    def set_active(self, active: bool) -> None:
        """Pencere kucultuldu/gizlendi ise animasyonu durdur (bosuna CPU yakma)."""
        self._active = active
        if active and self.isVisible():
            self._last_tick = time.monotonic()
            self._timer.start()
        elif not active:
            self._timer.stop()

    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._active and not self._timer.isActive():
            self._last_tick = time.monotonic()
            self._timer.start()
        super().showEvent(event)

    def set_center_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, float(level)))

    def set_center_mode(self, mode: str) -> None:
        if mode in _MODE_COLOR:
            self._mode = mode

    def set_agent_status(self, name: str, status: str) -> None:
        for dep, nodes in self._agents.items():
            for node in nodes:
                if node.key != name:
                    continue
                self._apply_status(node, status)
                # departmani da yak
                for d in self._departments:
                    if d.key == dep:
                        self._apply_status(d, status if status in _ACTIVE else "idle")
                return

    def expand(self, dept_key: str) -> None:
        self._expanded = None if self._expanded == dept_key else dept_key
        self.update()

    # ------------------------------------------------------------- internal
    @staticmethod
    def _apply_status(node: _Node, status: str) -> None:
        if status in _ACTIVE:
            node.target = 1.0
        elif status == "done":
            node.target, node.flash = 0.0, 1.0
            node.flash_color = QColor(theme.GOOD)
        elif status in ("failed", "blocked", "cancelled"):
            node.target, node.flash = 0.0, 1.0
            node.flash_color = QColor(theme.BAD)
        else:
            node.target = 0.0

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.25, max(0.0, now - self._last_tick))
        self._last_tick = now
        f = dt / 0.033          # 30 FPS'e gore normallestirilmis kare sayisi

        def ease(k: float) -> float:
            return 1.0 - (1.0 - k) ** f

        k = ease(0.5) if self._target_level > self._level else ease(0.10)
        self._level += (self._target_level - self._level) * k
        self._t += dt * 0.485   # eski hiz: tick basina 0.016 @ 33 ms
        node_ease = ease(0.14)
        busy = self._mode != "idle" or self._level > 0.02
        for node in self._iter_nodes():
            node.activity += (node.target - node.activity) * node_ease
            if node.flash > 0:
                node.flash = max(0.0, node.flash - 0.028 * f)
            if node.target > 0 or node.activity > 0.02 or node.flash > 0:
                busy = True
        want = self.BUSY_MS if busy else self.IDLE_MS
        if self._timer.interval() != want:
            self._timer.setInterval(want)
        self.update()

    def _iter_nodes(self):
        yield from self._departments
        for lst in self._agents.values():
            yield from lst

    def _geometry(self):
        w, h = self.width(), self.height()
        c = QPointF(w / 2.0, h / 2.0)
        ring = min(w, h) * 0.5 - 86
        ring = max(80.0, ring)
        drift = self._t * 0.05
        rr = ring + 66
        for d in self._departments:
            a = d.angle + drift
            d.pos = QPointF(c.x() + ring * math.cos(a), c.y() + ring * math.sin(a))
            agents = self._agents.get(d.key, [])
            step = self._fan_step(len(agents), rr)
            if d.key == self._expanded:
                self._label_w = int(max(56, min(116, step * rr - 8)))
            for ag in agents:
                aa = d.angle + ag.slot * step + drift
                ag.pos = QPointF(c.x() + rr * math.cos(aa), c.y() + rr * math.sin(aa))
        core_r = min(w, h) * 0.10
        return c, ring, max(24.0, core_r)

    @classmethod
    def _fan_step(cls, m: int, rr: float) -> float:
        """Komsu ajanlar arasi aci: etiketler cakismasin diye yay uzunlugu >= AGENT_GAP_PX,
        ama yelpaze FAN_MAX_RAD'i gecmesin (kalabalik departmanda etiket daralir)."""
        if m <= 1:
            return 0.42
        step = max(0.42, cls.AGENT_GAP_PX / max(rr, 1.0))
        return min(step, cls.FAN_MAX_RAD / (m - 1))

    def _hit(self, p: QPointF) -> _Node | None:
        """Tiklanan/uzerine gelinen dugum: en yakin olan (oklid), yaricapin ~1.6 kati icinde."""
        candidates: list[tuple[_Node, float]] = []
        if self._expanded:
            candidates += [(ag, self.AGENT_R * 1.6) for ag in self._agents.get(self._expanded, [])]
        candidates += [(d, self.DEPT_R * 1.6) for d in self._departments]
        best, best_d = None, float("inf")
        for node, limit in candidates:
            dist = math.hypot(p.x() - node.pos.x(), p.y() - node.pos.y())
            if dist <= limit and dist < best_d:
                best, best_d = node, dist
        return best

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        node = self._hit(event.position())
        if node is None:
            self._expanded = None
            self.update()
        elif node.kind == "agent":
            self.node_clicked.emit(node.key)
            self.agent_clicked.emit(node.key)
        else:
            self.expand(node.key)
            self.node_clicked.emit(f"dept:{node.key}")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        node = self._hit(event.position())
        if node is None:
            self.unsetCursor()
            QToolTip.hideText()
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if node.kind == "agent":   # daraltilmis etiketin tam hali
            QToolTip.showText(event.globalPosition().toPoint(), node.title, self)

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c, ring, core_r = self._geometry()
        self._draw_backdrop(p, c, ring)   # statik katman onbellekten + suren tarama cizgileri

        for d in self._departments:
            self._draw_edge(p, c, d.pos, d, thick=1.6)
        if self._expanded:
            dep = next((d for d in self._departments if d.key == self._expanded), None)
            if dep is not None:
                for ag in self._agents.get(self._expanded, []):
                    self._draw_edge(p, dep.pos, ag.pos, ag, thick=1.2)

        self._draw_core(p, c, core_r)

        for d in self._departments:
            self._draw_department(p, d)
        if self._expanded:
            for ag in self._agents.get(self._expanded, []):
                self._draw_agent(p, ag)
        p.end()

    def _draw_backdrop(self, p: QPainter, c: QPointF, ring: float) -> None:
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._static is None or self._static_key != key:
            self._static = self._render_static(c, ring, dpr)
            self._static_key = key
            self.static_renders += 1
        p.drawPixmap(0, 0, self._static)
        # Yalnizca zamana bagli kisim: donen tarama cizgileri
        sweep = self._k.ACCENT
        rr = ring * 1.36
        for j in range(22):
            a = -self._t * 0.8 - j * 0.055
            p.setPen(QPen(_rgba(sweep, int(55 * (1 - j / 22))), 1.4))
            p.drawLine(c, QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a)))

    def _render_static(self, c: QPointF, ring: float, dpr: float) -> QPixmap:
        """Izgara halkalari, isinlar ve kose isaretleri (zamandan bagimsiz)."""
        w, h = self.width(), self.height()
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        grid = self._k.GRID
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in (0.5, 0.78, 1.05, 1.35):
            p.setPen(QPen(_rgba(grid, 80), 1.0))
            p.drawEllipse(c, ring * k, ring * k)
        p.setPen(QPen(_rgba(grid, 55), 1.0))
        for i in range(30):
            a = i / 30 * math.tau
            r1, r2 = ring * 0.45, ring * 1.4
            p.drawLine(QPointF(c.x() + r1 * math.cos(a), c.y() + r1 * math.sin(a)),
                       QPointF(c.x() + r2 * math.cos(a), c.y() + r2 * math.sin(a)))
        p.setPen(QPen(_rgba(self._k.ACCENT, 110), 1.4))
        m, seg = 12, 18
        for x, y, dx, dy in ((m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
            p.drawLine(x, y, x + dx * seg, y)
            p.drawLine(x, y, x, y + dy * seg)
        p.end()
        return pm

    def _draw_edge(self, p: QPainter, a: QPointF, b: QPointF, node: _Node, thick: float) -> None:
        act = node.activity
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        nx, ny = -(b.y() - a.y()), (b.x() - a.x())
        nl = math.hypot(nx, ny) or 1.0
        bow = 14.0 * math.sin(self._t * 0.7 + node.angle)
        ctrl = QPointF(mid.x() + nx / nl * bow, mid.y() + ny / nl * bow)
        path = QPainterPath(a)
        path.quadTo(ctrl, b)
        p.setPen(QPen(_rgba(self._k.BORDER_LIGHT, 100), thick * 0.7))
        p.drawPath(path)
        if act > 0.02:
            glow = self._k.ACCENT
            p.setPen(QPen(_rgba(glow, int(45 + 130 * act)), thick + 2.4 * act))
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(4):
                t = (self._t * 1.7 + i / 4) % 1.0
                p.setBrush(_rgba(glow, int(230 * act)))
                p.drawEllipse(path.pointAtPercent(t), 2.5, 2.5)

    def _draw_core(self, p: QPainter, c: QPointF, r: float) -> None:
        color = _MODE_COLOR[self._mode]
        breath = 0.5 + 0.5 * math.sin(self._t * 2.2)
        energy = self._level if self._mode != "idle" else 0.14 + 0.10 * breath
        energy = max(0.0, min(1.0, energy))
        for k, aa in ((3.0, 45), (2.0, 75), (1.4, 120)):
            grad = QRadialGradient(c, r * k * (1 + 0.2 * energy))
            grad.setColorAt(0.0, _rgba(color, int(aa * (0.5 + energy))))
            grad.setColorAt(1.0, _rgba(color, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(c, r * k * (1 + 0.2 * energy), r * k * (1 + 0.2 * energy))
        # mistik rune halkasi
        p.setPen(QPen(_rgba(self._k.MYSTIC, 140), 1.8))
        rr = r * 1.8
        for i in range(36):
            if (i + int(self._t * 5)) % 3 == 0:
                continue
            a0 = i / 36 * math.tau + self._t * 0.5
            p.drawArc(int(c.x() - rr), int(c.y() - rr), int(rr * 2), int(rr * 2),
                      int(-math.degrees(a0) * 16), int(-math.degrees(math.tau / 36 * 0.55) * 16))
        # es-merkezli halkalar + donen ucgen
        for rad, wdt, al in ((r * 1.1, 2.0, 200), (r * 0.85, 5.0, 60), (r * 0.85, 2.0, 230)):
            p.setPen(QPen(_rgba(color, al), wdt))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rad, rad)
        tri = QPolygonF()
        tr = r * (0.5 + 0.28 * energy)
        for i in range(3):
            a = -math.pi / 2 + i * math.tau / 3 + self._t * 0.7
            tri.append(QPointF(c.x() + tr * math.cos(a), c.y() + tr * math.sin(a)))
        cg = QRadialGradient(c, tr * 1.4)
        cg.setColorAt(0.0, _rgba(color, int(210 + 40 * energy)))
        cg.setColorAt(1.0, _rgba(color, 40))
        p.setPen(QPen(_rgba(color, 220), 1.6))
        p.setBrush(cg)
        p.drawPolygon(tri)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_rgba(self._k.WHITE, int(150 + 90 * energy)))
        p.drawEllipse(c, r * 0.16, r * 0.16)
        p.setPen(QPen(_rgba(self._k.TEXT, 230)))
        f = p.font(); f.setPointSize(8); f.setBold(True)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 3)
        p.setFont(f)
        p.drawText(int(c.x() - 55), int(c.y() + r * 2.1), 110, 16,
                   Qt.AlignmentFlag.AlignHCenter, "C Y R A E N")

    def _draw_department(self, p: QPainter, node: _Node) -> None:
        pos, act = node.pos, node.activity
        nr = self.DEPT_R
        expanded = self._expanded == node.key
        col = self._k.ACCENT
        if node.flash > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(node.flash_color, int(130 * node.flash)))
            p.drawEllipse(pos, nr * (1.7 + node.flash), nr * (1.7 + node.flash))
        if act > 0.04 or expanded:
            g = QRadialGradient(pos, nr * 2.3)
            g.setColorAt(0.0, _rgba(col, int(150 * max(act, 0.5 if expanded else 0))))
            g.setColorAt(1.0, _rgba(col, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(pos, nr * 1.5, nr * 1.5)
        hexp = QPolygonF()
        for i in range(6):
            a = math.pi / 6 + i * math.tau / 6
            hexp.append(QPointF(pos.x() + nr * math.cos(a), pos.y() + nr * math.sin(a)))
        p.setPen(QPen(_rgba(col if (act > 0.1 or expanded) else self._k.BORDER_LIGHT, 235),
                      1.6 + 1.6 * act))
        p.setBrush(_rgba(self._k.BG_CARD, 240))
        p.drawPolygon(hexp)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_rgba(col, int(90 + 140 * max(act, 0.4 if expanded else 0))))
        p.drawEllipse(pos, nr * 0.32, nr * 0.32)
        p.setPen(QPen(_rgba(self._k.TEXT, 235)))
        f = p.font(); f.setPointSize(7); f.setBold(True)
        p.setFont(f)
        p.drawText(int(pos.x() - 90), int(pos.y() + nr + 4), 180, 14,
                   Qt.AlignmentFlag.AlignHCenter, tr_upper(node.title))

    def _draw_agent(self, p: QPainter, node: _Node) -> None:
        pos, act = node.pos, node.activity
        nr = self.AGENT_R
        col = _AUTONOMY_COLOR.get(node.autonomy, self._k.ACCENT_DIM)
        if node.flash > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(node.flash_color, int(140 * node.flash)))
            p.drawEllipse(pos, nr * (1.8 + node.flash), nr * (1.8 + node.flash))
        if act > 0.04:
            pulse = 1.3 + 0.3 * math.sin(self._t * 7)
            g = QRadialGradient(pos, nr * 2.5)
            g.setColorAt(0.0, _rgba(col, int(150 * act)))
            g.setColorAt(1.0, _rgba(col, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(pos, nr * pulse, nr * pulse)
        p.setPen(QPen(_rgba(col, 235), 1.4 + 1.4 * act))
        p.setBrush(_rgba(self._k.BG_CARD, 240))
        p.drawEllipse(pos, nr, nr)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_rgba(col, int(90 + 150 * act)))
        p.drawEllipse(pos, nr * 0.34, nr * 0.34)
        p.setPen(QPen(_rgba((self._k.TEXT if act > 0.1 else self._k.TEXT_DIM), 235)))
        f = p.font(); f.setPointSize(7); f.setBold(act > 0.1)
        p.setFont(f)
        lw = self._label_w
        text = QFontMetrics(f).elidedText(node.title, Qt.TextElideMode.ElideRight, lw)
        p.drawText(int(pos.x() - lw / 2), int(pos.y() + nr + 3), lw, 14,
                   Qt.AlignmentFlag.AlignHCenter, text)


_DEP_TITLE = DEPARTMENT_TITLES
