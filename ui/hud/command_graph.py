"""Komuta grafi - donen 3B yorunge: parcacik kuresi + departman halkasi + ajan rozet halkasi.

Merkezde sese tepki veren parcacik kuresi (JARVIS). Departmanlar ic, TUM ajanlar dis
yorungede durur; yorunge duzlemi izleyiciye dogru yatiktir ve yavasca doner. Ondeki
dugumler buyuk/parlak, arkadakiler kucuk/soluk cizilir (perspektif + derinlik sirasi).
Fareyle surukleyince graf elle doner. Durum/animasyon mantigi `BrainGraph`'tan gelir;
burada yalnizca yerlesim ve cizim degisir.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QToolTip

from ui import theme
from ui.strings import tr_upper
from ui.widgets.brain_graph import _MODE_COLOR, BrainGraph, _Node, _rgba

PARTICLES = 420
DUST = 90
_SEED = 7
TILT = math.radians(52)        # yorunge duzleminin yatikligi (0 = tam karsidan)
FOCAL = 3.2                    # perspektif: kamera uzakligi / dis yaricap
SPIN_PER_T = 0.144             # otomatik donus (rad / _t birimi) ~ 90 sn'de bir tur
DRAG_RAD_PER_PX = 0.008
DRAG_THRESHOLD_PX = 4.0
RING_SEGMENTS = 96
_COS_T, _SIN_T = math.cos(TILT), math.sin(TILT)


class CommandGraph(BrainGraph):
    DEPT_R = 6.5
    AGENT_R = 13.0

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        rng = random.Random(_SEED)
        # Cekirdek: birim kure icinde/ustunde noktalar (x, y, z, faz)
        self._particles: list[tuple[float, float, float, float]] = []
        for i in range(PARTICLES):
            y = 1.0 - 2.0 * (i + 0.5) / PARTICLES            # fibonacci kuresi
            ring = math.sqrt(max(0.0, 1.0 - y * y))
            a = i * 2.399963
            k = 1.0 if i % 3 else rng.uniform(0.25, 0.85)     # ucte biri icte: dolu gorunsun
            self._particles.append((ring * math.cos(a) * k, y * k, ring * math.sin(a) * k,
                                    rng.uniform(0, math.tau)))
        # (aci, 0..1 konum) - yorunge duzlemindeki toz
        self._dust = [(rng.uniform(0, math.tau), rng.random()) for _ in range(DUST)]
        self._dept_color: dict[str, QColor] = {}
        self._rings = (0.0, 0.0, 0.0)   # ic, dis, cekirdek yaricapi (son geometri)
        self._center = QPointF()
        self._rot = 0.0                 # yorungenin donus acisi (otomatik + surukleme)
        self._press: QPointF | None = None
        self._dragging = False

    # ------------------------------------------------------------------ API
    def set_agents(self, agents: list) -> None:
        super().set_agents(agents)
        self._color_departments()
        # Dis halka: ajanlar departman sirasiyla esit aralikli; departman kendi ajanlarinin ortasinda
        total = sum(len(self._agents[d.key]) for d in self._departments) or 1
        i = 0
        for d in self._departments:
            nodes = self._agents[d.key]
            for ag in nodes:
                ag.angle = -math.pi / 2 + (i + 0.5) / total * math.tau
                ag.slot = float(i)   # dis halkadaki sira (komsu etiketler kademeli cizilir)
                i += 1
            if nodes:
                d.angle = sum(ag.angle for ag in nodes) / len(nodes)
        self.update()

    def refresh_theme(self) -> None:
        super().refresh_theme()
        self._color_departments()

    def _color_departments(self) -> None:
        palette = [QColor(c) for c in theme.DEPT_COLORS]
        self._dept_color = {d.key: palette[i % len(palette)] for i, d in enumerate(self._departments)}

    # ------------------------------------------------------------- internal
    def _tick(self) -> None:
        before = self._t
        super()._tick()
        if not self._dragging:
            self._rot += (self._t - before) * SPIN_PER_T

    def _color_of(self, node: _Node) -> QColor:
        return self._dept_color.get(node.parent or node.key, self._k.ACCENT)

    def _project(self, angle: float, radius: float) -> tuple[QPointF, float, float]:
        """Yorunge duzlemindeki (aci, yaricap) noktasinin ekran konumu, olcegi ve derinligi.

        Derinlik -1 (en arka) .. +1 (en on); olcek ondekiler icin > 1.
        """
        outer = self._rings[1] or 1.0
        x = radius * math.cos(angle)
        zp = radius * math.sin(angle)              # duzlem ici "ileri-geri" ekseni (+ = izleyiciye)
        scale = FOCAL / (FOCAL - (zp * _SIN_T) / outer)
        c = self._center
        return QPointF(c.x() + x * scale, c.y() + zp * _COS_T * scale), scale, zp / outer

    def _geometry(self):  # noqa: ANN202
        w, h = self.width(), self.height()
        near = _COS_T * FOCAL / (FOCAL - _SIN_T)   # dis halkanin alt (on) ucu, yaricap biriminde
        far = _COS_T * FOCAL / (FOCAL + _SIN_T)    # ust (arka) ucu
        outer = max(110.0, min(w / 2.0 - 56.0, (h - 84.0) / (near + far)))
        inner = outer * 0.5
        core = outer * 0.24
        self._rings = (inner, outer, core)
        self._center = QPointF(w / 2.0, h / 2.0 - (near - far) / 2.0 * outer)
        for d in self._departments:
            d.pos, d.scale, d.depth = self._project(d.angle + self._rot, inner)
            for ag in self._agents.get(d.key, []):
                ag.pos, ag.scale, ag.depth = self._project(ag.angle + self._rot, outer)
        return self._center, inner, outer, core

    def _hit(self, p: QPointF) -> _Node | None:
        best, best_key = None, (-2.0, 0.0)
        for node in self._iter_nodes():
            base = self.AGENT_R * 1.35 if node.kind == "agent" else self.DEPT_R * 2.6
            dist = math.hypot(p.x() - node.pos.x(), p.y() - node.pos.y())
            if dist <= base * getattr(node, "scale", 1.0):
                key = (getattr(node, "depth", 0.0), -dist)   # ust uste gelirse ondeki kazanir
                if best is None or key > best_key:
                    best, best_key = node, key
        return best

    # ------------------------------------------------------------------ fare
    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        self._press = event.position()
        self._dragging = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        pos = event.position()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            dx = pos.x() - self._press.x()
            if self._dragging or abs(dx) > DRAG_THRESHOLD_PX:
                self._dragging = True
                self._rot -= dx * DRAG_RAD_PER_PX
                self._press = pos
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                QToolTip.hideText()
                self.update()
            return
        node = self._hit(pos)
        if node is None:
            self.unsetCursor()
            QToolTip.hideText()
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        tip = node.title
        if node.kind == "department":
            tip = f"{node.title} · {len(self._agents.get(node.key, []))} ajan"
        QToolTip.showText(event.globalPosition().toPoint(), tip, self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        dragged, self._dragging, self._press = self._dragging, False, None
        if dragged:
            self.unsetCursor()
            return
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

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c, inner, outer, core = self._geometry()

        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._static is None or self._static_key != key:
            self._static = self._render_static(c, inner, dpr)
            self._static_key = key
            self.static_renders += 1
        p.drawPixmap(0, 0, self._static)
        self._draw_dust(p, core, inner)

        for d in self._departments:
            self._draw_link(p, c, d.pos, d, base_alpha=70, depth=d.depth * 0.5)
            lit = d.key == self._expanded
            for ag in self._agents.get(d.key, []):
                self._draw_link(p, d.pos, ag.pos, ag, base_alpha=90 if lit else 34, depth=ag.depth)

        total = max(1, sum(len(v) for v in self._agents.values()))
        label_w = int(max(40.0, min(110.0, math.tau / total * outer * 1.9)))
        core_drawn = False
        for node in sorted(self._iter_nodes(), key=lambda n: n.depth):   # arkadan one
            if not core_drawn and node.depth >= 0.0:
                self._draw_core(p, c, core)
                core_drawn = True
            if node.kind == "agent":
                self._draw_agent(p, node, label_w)
            else:
                self._draw_department(p, node, c)
        if not core_drawn:
            self._draw_core(p, c, core)
        p.end()

    def _render_static(self, c: QPointF, inner: float, dpr: float) -> QPixmap:  # type: ignore[override]
        """Yorunge halkalari (donusten bagimsiz): on yay parlak, arka yay soluk + zemin isimasi."""
        w, h = self.width(), self.height()
        _inner, outer, _core = self._rings
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # cekirdegin yorunge duzlemine dusen isigi
        p.save()
        p.translate(c)
        p.scale(1.0, _COS_T)
        floor = QRadialGradient(QPointF(0, 0), inner * 1.15)
        floor.setColorAt(0.0, _rgba(self._k.ACCENT, 34))
        floor.setColorAt(1.0, _rgba(self._k.ACCENT, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(floor)
        p.drawEllipse(QPointF(0, 0), inner * 1.15, inner * 1.15)
        p.restore()

        for radius, strength in ((inner, 1.0), ((inner + outer) / 2, 0.55), (outer, 1.0)):
            prev, _s, _d = self._project(0.0, radius)
            for i in range(1, RING_SEGMENTS + 1):
                cur, _s, depth = self._project(i / RING_SEGMENTS * math.tau, radius)
                near = (depth * outer / radius + 1.0) / 2.0     # 0 = arka yay, 1 = on yay
                p.setPen(QPen(_rgba(self._k.BORDER_LIGHT, int((40 + 170 * near) * strength)), 0.8 + 0.9 * near))
                p.drawLine(prev, cur)
                prev = cur
        p.end()
        return pm

    def _draw_dust(self, p: QPainter, core: float, inner: float) -> None:
        lo, hi = core * 2.0, inner * 0.94
        back, front = QPolygonF(), QPolygonF()
        for ang, k in self._dust:
            pos, _s, depth = self._project(ang + self._rot * 0.6, lo + (hi - lo) * k)
            (front if depth >= 0 else back).append(pos)
        pen = QPen(_rgba(self._k.ACCENT, 38), 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPoints(back)
        pen.setColor(_rgba(self._k.ACCENT, 85))
        pen.setWidthF(1.7)
        p.setPen(pen)
        p.drawPoints(front)

    @staticmethod
    def _fade(depth: float) -> float:
        """Derinlik -> gorunurluk carpani (arka 0.38 .. on 1.0)."""
        return 0.38 + 0.62 * (max(-1.0, min(1.0, depth)) + 1.0) / 2.0

    def _draw_link(self, p: QPainter, a: QPointF, b: QPointF, node: _Node, base_alpha: int,
                   depth: float = 0.0) -> None:
        col = self._color_of(node)
        act = node.activity
        p.setPen(QPen(_rgba(self._k.BORDER_LIGHT, int(base_alpha * self._fade(depth))), 1.0))
        p.drawLine(a, b)
        if act > 0.02:
            p.setPen(QPen(_rgba(col, int(60 + 150 * act)), 1.0 + 1.6 * act))
            p.drawLine(a, b)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(col, int(235 * act)))
            for i in range(3):
                t = (self._t * 1.7 + i / 3) % 1.0
                p.drawEllipse(QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t), 2.2, 2.2)

    def _draw_core(self, p: QPainter, c: QPointF, r: float) -> None:
        color = _MODE_COLOR[self._mode] if self._mode != "idle" else self._k.ACCENT
        breath = 0.5 + 0.5 * math.sin(self._t * 2.2)
        energy = self._level if self._mode != "idle" else 0.10 + 0.08 * breath
        energy = max(0.0, min(1.0, energy))
        dim = 0.6 if self._mode == "idle" else 1.0
        radius = r * (1.0 + 0.45 * energy)

        glow = QRadialGradient(c, radius * 2.1)
        glow.setColorAt(0.0, _rgba(color, int((46 + 90 * energy) * dim)))
        glow.setColorAt(1.0, _rgba(color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, radius * 2.1, radius * 2.1)

        # kure govdesi: sol ustten isik alan yari saydam hacim + ince kenar
        shell = QRadialGradient(QPointF(c.x() - radius * 0.35, c.y() - radius * 0.4), radius * 1.5)
        shell.setColorAt(0.0, _rgba(color, int(58 * dim)))
        shell.setColorAt(0.7, _rgba(color, int(14 * dim)))
        shell.setColorAt(1.0, _rgba(color, 0))
        p.setPen(QPen(_rgba(color, int(70 * dim)), 1.0))
        p.setBrush(shell)
        p.drawEllipse(c, radius, radius)

        spin = self._t * 0.55
        cs, sn = math.cos(spin), math.sin(spin)
        ct, st = math.cos(0.38), math.sin(0.38)       # kure ekseni hafif one yatik
        back, mid, front = QPolygonF(), QPolygonF(), QPolygonF()
        for x, y, z, phase in self._particles:
            k = 1.0 + 0.06 * math.sin(self._t * 2.6 + phase)
            xr, zr = x * cs + z * sn, -x * sn + z * cs          # Y ekseninde donus
            yr, zd = y * ct - zr * st, y * st + zr * ct         # X ekseninde yatirma
            persp = 1.0 + 0.22 * zd
            pt = QPointF(c.x() + xr * radius * k * persp, c.y() + yr * radius * k * persp)
            (front if zd > 0.33 else mid if zd > -0.33 else back).append(pt)
        pen = QPen(color, 1.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for pts, alpha, width in ((back, 80, 1.2), (mid, 165, 1.8), (front, 250, 2.5)):
            pen.setColor(_rgba(color, int(alpha * dim)))
            pen.setWidthF(width)
            p.setPen(pen)
            p.drawPoints(pts)

    def _draw_department(self, p: QPainter, node: _Node, c: QPointF) -> None:  # type: ignore[override]
        pos, act = node.pos, node.activity
        fade = self._fade(node.depth)
        nr = self.DEPT_R * node.scale
        col = self._color_of(node)
        expanded = self._expanded == node.key
        strong = expanded or act > 0.1
        if node.flash > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(node.flash_color, int(130 * node.flash)))
            p.drawEllipse(pos, nr * (2.0 + node.flash), nr * (2.0 + node.flash))
        if act > 0.04 or expanded:
            g = QRadialGradient(pos, nr * 3.4)
            g.setColorAt(0.0, _rgba(col, int(170 * max(act, 0.55 if expanded else 0))))
            g.setColorAt(1.0, _rgba(col, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(pos, nr * 3.4, nr * 3.4)
        # kure hissi: sol ustten isik alan dolgu
        alpha = 255 if strong else int(255 * fade)
        ball = QRadialGradient(QPointF(pos.x() - nr * 0.35, pos.y() - nr * 0.4), nr * 1.5)
        ball.setColorAt(0.0, _rgba(col.lighter(150), alpha))
        ball.setColorAt(1.0, _rgba(col.darker(170), alpha))
        p.setPen(QPen(_rgba(self._k.BG_CARD, 255), 1.6))
        p.setBrush(ball)
        p.drawEllipse(pos, nr, nr)

        f = QFont(p.font())
        f.setPointSizeF(7.0 + 1.6 * (node.scale - 0.8))
        f.setBold(strong)
        p.setFont(f)
        p.setPen(QPen(_rgba(col if strong else self._k.TEXT_DIM, alpha)))
        room = 96
        text = QFontMetrics(f).elidedText(node.title, Qt.TextElideMode.ElideRight, room)
        dx = pos.x() - c.x()
        if abs(dx) < self._rings[0] * 0.3:   # merkez hizasinda: etiket dugumun altinda/ustunde
            y = pos.y() + (nr + 3 if node.depth >= 0 else -nr - 17)
            p.drawText(QRectF(pos.x() - room / 2, y, room, 14), Qt.AlignmentFlag.AlignHCenter, text)
        elif dx > 0:
            p.drawText(QRectF(pos.x() + nr + 6, pos.y() - 7, room, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        else:
            p.drawText(QRectF(pos.x() - nr - 6 - room, pos.y() - 7, room, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_agent(self, p: QPainter, node: _Node, label_w: int) -> None:  # type: ignore[override]
        pos, act = node.pos, node.activity
        fade = self._fade(node.depth)
        nr = self.AGENT_R * node.scale
        col = self._color_of(node)
        lit = self._expanded == node.parent
        faded = self._expanded is not None and not lit and act < 0.05
        if node.flash > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(node.flash_color, int(140 * node.flash)))
            p.drawEllipse(pos, nr * (1.5 + node.flash), nr * (1.5 + node.flash))
        if act > 0.04:
            pulse = 1.9 + 0.3 * math.sin(self._t * 7)
            g = QRadialGradient(pos, nr * pulse)
            g.setColorAt(0.0, _rgba(col, int(160 * act)))
            g.setColorAt(1.0, _rgba(col, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(pos, nr * pulse, nr * pulse)
        # zemindeki golge + ustten isik alan rozet
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, int(90 * fade)))
        p.drawEllipse(QPointF(pos.x(), pos.y() + nr * 0.28), nr * 1.02, nr * 0.92)
        vis = 1.0 if lit else fade
        ring_alpha = 45 if faded else int(min(255.0, ((235 if lit else 150) + 105 * act) * vis))
        body = QRadialGradient(QPointF(pos.x() - nr * 0.3, pos.y() - nr * 0.45), nr * 1.6)
        body.setColorAt(0.0, self._k.BORDER_LIGHT)
        body.setColorAt(1.0, self._k.BG_CARD)
        p.setPen(QPen(_rgba(col, ring_alpha), (1.1 + 1.2 * act) * node.scale))
        p.setBrush(body)
        p.drawEllipse(pos, nr, nr)

        f = QFont(p.font())
        f.setPointSizeF(max(6.0, 8.0 * node.scale))
        f.setBold(True)
        p.setFont(f)
        ink = col if (lit or act > 0.1) else self._k.TEXT_DIM
        p.setPen(QPen(_rgba(ink, 70 if faded else int(250 * vis))))
        p.drawText(QRectF(pos.x() - nr, pos.y() - nr, nr * 2, nr * 2), Qt.AlignmentFlag.AlignCenter,
                   tr_upper(node.title[:1]))
        if lit or act > 0.1:
            f.setPointSizeF(7.0)
            f.setBold(act > 0.1)
            p.setFont(f)
            p.setPen(QPen(_rgba(self._k.TEXT, 235)))
            text = QFontMetrics(f).elidedText(node.title, Qt.TextElideMode.ElideRight, label_w)
            # komsu etiketler cakismasin: tek siradakiler rozetin ustune, ciftler altina
            y = pos.y() - nr - 15 if int(node.slot) % 2 else pos.y() + nr + 2
            p.drawText(QRectF(pos.x() - label_w / 2, y, label_w, 13),
                       Qt.AlignmentFlag.AlignHCenter, text)
