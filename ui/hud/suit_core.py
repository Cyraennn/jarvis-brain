"""HUD merkezi: holografik Iron Man zirh bustu + gogus arc reactor'u.

Referans: Stark/JARVIS masaustu temasi. Cizim `DESIGN_W x DESIGN_H` tasarim biriminde yapilir
(x: bust merkezine gore -550..550, y: 0..1000) ve widget'a olceklenir.

- Zirh cizgileri, zirh ici izgara, kirmizi boyun kablolari, sol ustteki reactor taslaginin
  sabit kisimlari ve sag ustteki departman kadraninin yaylari STATIK katmanda (boyut
  degismedikce bir kez pixmap'e) cizilir.
- Her karede: goz parlamasi, arc reactor (ses seviyesiyle nabiz), donen taslak kanatlari,
  holografik tarama cizgisi, departman isaretleri/etiketleri ve guc satiri.

`BrainGraph` ile ayni API'yi sunar (`set_agents`, `set_agent_status`, `set_center_level`,
`set_center_mode`, `set_active`, `expand`, `node_clicked`), boylece `MainWindow`
handler'lari degismeden calisir. Ajan ayrintisi sag ustteki AJANLAR kartindadir; burada
departman kadrani vardir (tiklaninca `node_clicked("dept:<key>")`).
"""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QToolTip, QWidget

from ui import theme
from ui.strings import DEPARTMENT_TITLES, tr_upper

DESIGN_W = 1240.0          # sag ustteki kadran etiketleri icin bust'in yanlarinda pay
DESIGN_H = 1000.0

SUIT = QColor(38, 170, 222)          # zirh cizgisi (referanstaki mavi-camgobegi)
SUIT_DIM = QColor(38, 170, 222, 70)
WIRE_RED = QColor(232, 64, 84)
DIAL_ORANGE = QColor(232, 97, 44)
SKETCH = QColor(190, 200, 210)
EYE = QColor(170, 245, 255)

REACTOR_C = (0.0, 815.0)
REACTOR_R = 78.0
DIAL_C = (330.0, 285.0)
DIAL_R = 92.0
SKETCH_C = (-375.0, 300.0)
SKETCH_R = 82.0

_MODE_HALO = {
    "idle": QColor(theme.ACCENT_DIM),
    "listening": QColor(theme.ACCENT),
    "speaking": QColor(theme.GOLD),
}
_ACTIVE = {"queued", "routing", "running", "tool", "awaiting_approval"}
# kadranda yer dar: uzun departman adlarinin kisa hali
DIAL_SHORT = {"gunluk": "Günlük"}
TREND_WINDOW_S = 1.0


# ------------------------------------------------------------------ geometri
def _mirror(right: list[tuple[float, float]]) -> QPolygonF:
    """Merkez ustten baslayip sag yarimdan asagi inen noktalardan simetrik kapali cokgen."""
    pts = [QPointF(x, y) for x, y in right]
    pts += [QPointF(-x, y) for x, y in reversed(right[1:-1])]
    return QPolygonF(pts)


def _poly(points: list[tuple[float, float]], closed: bool = True) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    if closed:
        path.closeSubpath()
    return path


def _both(points: list[tuple[float, float]], closed: bool = True) -> QPainterPath:
    """Sag yarim cizgiyi ve aynasini tek path'te dondurur."""
    path = _poly(points, closed)
    path.addPath(_poly([(-x, y) for x, y in points], closed))
    return path


HELMET = _mirror([(0, 62), (62, 66), (100, 84), (120, 120), (128, 170), (130, 240), (126, 300),
                  (116, 345), (92, 385), (52, 410), (0, 418)])
TORSO = _mirror([(0, 478), (126, 468), (250, 490), (250, 560), (300, 600), (380, 640), (390, 720),
                 (360, 800), (330, 880), (250, 940), (120, 965), (0, 970)])
SHOULDER_R = [(250, 490), (360, 520), (440, 560), (488, 620), (500, 700), (470, 722), (420, 690),
              (380, 640), (300, 600), (250, 560)]
ARM_R = [(420, 690), (470, 722), (492, 800), (474, 880), (424, 884), (406, 800)]
PEC_R = [(40, 630), (200, 612), (290, 650), (298, 715), (258, 758), (160, 745), (108, 702)]
EYE_R = [(20, 222), (98, 216), (104, 228), (90, 246), (30, 250)]


def _suit_outline() -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(HELMET)
    path.closeSubpath()
    path.addPolygon(TORSO)
    path.closeSubpath()
    path.addPath(_both(SHOULDER_R))
    path.addPath(_both(ARM_R))
    return path


def _suit_details() -> QPainterPath:
    p = QPainterPath()
    # kask: alin plakasi, kas, yuz plakasi kenari, yanak, agiz
    p.addPath(_poly([(-40, 66), (-44, 150), (-24, 192), (24, 192), (44, 150), (40, 66)], closed=False))
    p.addPath(_both([(24, 192), (110, 200), (128, 215)], closed=False))
    p.addPath(_poly([(-128, 215), (-112, 270), (-104, 330), (-78, 372), (-40, 392), (0, 396),
                     (40, 392), (78, 372), (104, 330), (112, 270), (128, 215)], closed=False))
    p.addPath(_both([(104, 258), (70, 300), (60, 340)], closed=False))
    p.addPath(_poly([(-52, 352), (52, 352)], closed=False))
    for x in (-20, 20):
        p.addPath(_poly([(x, 346), (x, 358)], closed=False))
    p.addPath(_both(EYE_R))
    # boyun
    p.addPath(_both([(60, 408), (66, 470)], closed=False))
    p.addPath(_both([(112, 372), (126, 468)], closed=False))
    for y in (430, 452):
        p.addPath(_both([(66, y), (120, y)], closed=False))
    # gogus plakalari, yan cizgiler, karin
    p.addPath(_both(PEC_R))
    p.addPath(_both([(258, 758), (300, 850)], closed=False))
    p.addPath(_both([(60, 862), (180, 880), (250, 920)], closed=False))
    p.addPath(_both([(0, 700), (108, 702)], closed=False))
    # arc reactor yuvasi
    p.addEllipse(QPointF(*REACTOR_C), REACTOR_R + 22, REACTOR_R + 22)
    return p


def _red_wiring() -> QPainterPath:
    p = QPainterPath()
    p.addPath(_poly([(-150, 482), (-70, 520), (-40, 560), (0, 580), (40, 560), (70, 520), (150, 482)],
                    closed=False))
    p.addPath(_both([(40, 560), (48, 610)], closed=False))
    p.addPath(_poly([(0, 580), (0, 625)], closed=False))
    p.addPath(_both([(180, 880), (200, 958)], closed=False))
    p.addPath(_both([(120, 905), (140, 962)], closed=False))
    for (x, y, r) in ((70, 520, 7), (40, 560, 6), (48, 612, 5), (200, 958, 5)):
        p.addEllipse(QPointF(x, y), r, r)
        p.addEllipse(QPointF(-x, y), r, r)
    p.addEllipse(QPointF(0, 628), 6, 6)
    return p


def _rgba(c: QColor, a: int) -> QColor:
    return QColor(c.red(), c.green(), c.blue(), max(0, min(255, a)))


def _cos_pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCosmetic(True)       # olcekten bagimsiz piksel kalinligi
    return pen


# ====================================================================== widget
class SuitCore(QWidget):
    BUSY_MS = 33
    IDLE_MS = 66
    node_clicked = Signal(str)     # "dept:<key>"
    agent_clicked = Signal(str)    # BrainGraph uyumlulugu (burada ajan dugumu yok)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 330)
        self.setMouseTracking(True)

        self._outline = _suit_outline()
        self._details = _suit_details()
        self._wiring = _red_wiring()

        self._depts: list[str] = []                 # departman anahtarlari (sirali)
        self._agent_dept: dict[str, str] = {}
        self._active_agents: dict[str, set[str]] = {}
        self._selected: str | None = None
        self._hover: str | None = None
        self._label_rects: dict[str, QRectF] = {}

        self._mode = "idle"
        self._level = 0.0
        self._target_level = 0.0
        self._history: deque[tuple[float, float]] = deque(maxlen=240)   # (zaman, seviye)
        self._t = 0.0

        self._static: QPixmap | None = None
        self._static_key: tuple | None = None
        self.static_renders = 0

        self._active = True
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self.BUSY_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------ API
    def set_agents(self, agents: list) -> None:
        depts: set[str] = set()
        self._agent_dept.clear()
        for spec in agents:
            dep = getattr(getattr(spec, "department", None), "value", None) or "genel"
            depts.add(dep)
            self._agent_dept[getattr(spec, "name", str(spec))] = dep
        self._depts = sorted(depts)
        self._active_agents = {d: set() for d in self._depts}
        self._static = None
        self.update()

    def set_agent_status(self, name: str, status: str) -> None:
        dep = self._agent_dept.get(name)
        if dep is None:
            return
        bucket = self._active_agents.setdefault(dep, set())
        if status in _ACTIVE:
            bucket.add(name)
        else:
            bucket.discard(name)

    def set_center_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, float(level)))

    def set_center_mode(self, mode: str) -> None:
        if mode in _MODE_HALO:
            self._mode = mode

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self.isVisible():
            self._last_tick = time.monotonic()
            self._timer.start()
        elif not active:
            self._timer.stop()

    def expand(self, dept_key: str) -> None:
        self._selected = None if self._selected == dept_key else dept_key
        self.update()

    def active_count(self, dept_key: str) -> int:
        return len(self._active_agents.get(dept_key, ()))

    def power_text(self) -> str:
        pct = round(self._level * 100)
        delta = self._level - self._level_ago(TREND_WINDOW_S)
        trend = "yükseliyor" if delta > 0.08 else "düşüyor" if delta < -0.08 else "sabit seyrediyor"
        return f"Güç seviyesi şu an %{pct} ve {trend}."

    def _level_ago(self, seconds: float) -> float:
        """~`seconds` once olculen seviye (kare hizindan bagimsiz); gecmis yoksa su anki."""
        cutoff = time.monotonic() - seconds
        for t, level in reversed(self._history):
            if t <= cutoff:
                return level
        return self._history[0][1] if self._history else self._level

    # ------------------------------------------------------------ zamanlama
    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._active and not self._timer.isActive():
            self._last_tick = time.monotonic()
            self._timer.start()
        super().showEvent(event)

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.25, max(0.0, now - self._last_tick))
        self._last_tick = now
        f = dt / 0.033
        k = 1.0 - (1.0 - (0.5 if self._target_level > self._level else 0.10)) ** f
        self._level += (self._target_level - self._level) * k
        self._history.append((now, self._level))
        self._t += dt
        busy = self._mode != "idle" or self._level > 0.02 or any(self._active_agents.values())
        want = self.BUSY_MS if busy else self.IDLE_MS
        if self._timer.interval() != want:
            self._timer.setInterval(want)
        self.update()

    # ------------------------------------------------------------ donusum
    def _transform(self) -> QTransform:
        w, h = self.width(), self.height()
        s = min(w / DESIGN_W, h / DESIGN_H)
        tr = QTransform()
        tr.translate(w / 2.0, (h - DESIGN_H * s) / 2.0)
        tr.scale(s, s)
        return tr

    def _scale(self) -> float:
        return min(self.width() / DESIGN_W, self.height() / DESIGN_H)

    # --------------------------------------------------------------- fare
    def _dept_at(self, pos: QPointF) -> str | None:
        for key, rect in self._label_rects.items():
            if rect.adjusted(-6, -4, 6, 4).contains(pos):
                return key
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        key = self._dept_at(event.position())
        if key is None:
            return
        self.expand(key)
        self.node_clicked.emit(f"dept:{key}")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        key = self._dept_at(event.position())
        if key != self._hover:
            self._hover = key
            self.update()
        if key is None:
            self.unsetCursor()
            QToolTip.hideText()
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        n = self.active_count(key)
        tip = f"{DEPARTMENT_TITLES.get(key, key)} — " + (f"{n} aktif görev" if n else "boşta") + "\nTıkla: ajanları göster"
        QToolTip.showText(event.globalPosition().toPoint(), tip, self)

    # ------------------------------------------------------------- cizim
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, tuple(self._depts))
        if self._static is None or self._static_key != key:
            self._static = self._render_static(dpr)
            self._static_key = key
            self.static_renders += 1
        p.drawPixmap(0, 0, self._static)

        tr = self._transform()
        p.save()
        p.setTransform(tr)
        self._draw_scan(p)
        self._draw_eyes(p)
        self._draw_sketch_rotor(p)
        self._draw_reactor(p)
        p.restore()
        self._draw_dial_labels(p, tr)
        self._draw_power(p, tr)
        p.end()

    def _render_static(self, dpr: float) -> QPixmap:
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setTransform(self._transform())

        # zirh ici izgara (hologram dokusu)
        p.save()
        p.setClipPath(self._outline)
        p.setPen(_cos_pen(_rgba(SUIT, 34), 1))
        step = 18
        for x in range(-520, 521, step):
            p.drawLine(QPointF(x, 40), QPointF(x, 990))
        for y in range(40, 991, step):
            p.drawLine(QPointF(-520, y), QPointF(520, y))
        p.fillPath(self._outline, _rgba(SUIT, 14))
        p.restore()

        # dis parlama + ana hatlar + detaylar
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_cos_pen(_rgba(SUIT, 45), 5))
        p.drawPath(self._outline)
        p.setPen(_cos_pen(SUIT, 1.6))
        p.drawPath(self._outline)
        p.setPen(_cos_pen(_rgba(SUIT, 200), 1.1))
        p.drawPath(self._details)
        # omuz eklemleri
        for sx in (-1, 1):
            c = QPointF(sx * 330, 665)
            p.drawEllipse(c, 30, 30)
            p.drawEllipse(c, 16, 16)
        # kirmizi kablolar
        p.setPen(_cos_pen(_rgba(WIRE_RED, 60), 4))
        p.drawPath(self._wiring)
        p.setPen(_cos_pen(WIRE_RED, 1.3))
        p.drawPath(self._wiring)

        self._draw_sketch_static(p)
        self._draw_dial_static(p)
        p.end()
        return pm

    # ---------------------------------------------------------- reactor
    def _draw_reactor(self, p: QPainter) -> None:
        c = QPointF(*REACTOR_C)
        r = REACTOR_R
        breath = 0.5 + 0.5 * math.sin(self._t * 2.2)
        energy = self._level if self._mode != "idle" else 0.18 + 0.12 * breath
        energy = max(0.0, min(1.0, energy))
        halo = _MODE_HALO[self._mode]

        glow_r = r * (2.0 + 0.9 * energy)
        g = QRadialGradient(c, glow_r)
        g.setColorAt(0.0, _rgba(QColor(200, 245, 255), int(150 + 90 * energy)))
        g.setColorAt(0.35, _rgba(halo, int(90 + 120 * energy)))
        g.setColorAt(1.0, _rgba(halo, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, glow_r, glow_r)

        # dis halka + kirmizi ic halka
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_cos_pen(_rgba(EYE, 230), 2.2))
        p.drawEllipse(c, r, r)
        p.setPen(_cos_pen(_rgba(WIRE_RED, 220), 2.4))
        p.drawEllipse(c, r * 0.62, r * 0.62)

        # donen bobin plakalari (ses seviyesiyle hizlanir)
        spin = self._t * (0.35 + 1.6 * energy)
        p.setPen(_cos_pen(_rgba(EYE, 200), 1.2))
        p.setBrush(_rgba(SUIT, int(110 + 100 * energy)))
        for i in range(10):
            a = spin + i * math.tau / 10
            poly = QPolygonF()
            for rr, da in ((r * 0.68, -0.18), (r * 0.94, -0.13), (r * 0.94, 0.13), (r * 0.68, 0.18)):
                poly.append(QPointF(c.x() + rr * math.cos(a + da), c.y() + rr * math.sin(a + da)))
            p.drawPolygon(poly)

        # cekirdek
        cg = QRadialGradient(c, r * 0.5)
        cg.setColorAt(0.0, QColor(255, 255, 255, 255))
        cg.setColorAt(0.5, _rgba(EYE, int(200 + 55 * energy)))
        cg.setColorAt(1.0, _rgba(SUIT, 60))
        p.setPen(_cos_pen(_rgba(EYE, 240), 1.4))
        p.setBrush(cg)
        p.drawEllipse(c, r * 0.42, r * 0.42)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_cos_pen(_rgba(SUIT, 220), 1.4))
        p.drawEllipse(c, r * 0.24, r * 0.24)
        p.drawEllipse(c, r * 0.12, r * 0.12)

    def _draw_eyes(self, p: QPainter) -> None:
        on = {"idle": 0.45, "listening": 0.85, "speaking": 1.0}[self._mode]
        on = min(1.0, on + 0.3 * self._level)
        path = _both(EYE_R)
        p.setPen(_cos_pen(_rgba(EYE, int(80 * on)), 7))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(_cos_pen(_rgba(QColor(255, 255, 255), int(220 * on)), 1.2))
        p.setBrush(_rgba(EYE, int(230 * on)))
        p.drawPath(path)

    def _draw_scan(self, p: QPainter) -> None:
        y = 40 + ((self._t * 0.16) % 1.0) * 950
        p.save()
        p.setClipPath(self._outline)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_rgba(SUIT, 26))
        p.drawRect(QRectF(-520, y - 26, 1040, 26))
        p.setPen(_cos_pen(_rgba(EYE, 90), 1))
        p.drawLine(QPointF(-520, y), QPointF(520, y))
        p.restore()

    # ---------------------------------------------------------- taslak (sol ust)
    def _draw_sketch_static(self, p: QPainter) -> None:
        cx, cy = SKETCH_C
        c = QPointF(cx, cy)
        r = SKETCH_R
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_cos_pen(_rgba(SKETCH, 150), 1))
        for k in (1.0, 0.82, 0.48, 0.26):
            p.drawEllipse(c, r * k, r * k)
        p.setPen(_cos_pen(_rgba(SKETCH, 90), 1))
        p.drawLine(QPointF(cx - r * 1.35, cy), QPointF(cx + r * 1.35, cy))
        p.drawLine(QPointF(cx, cy - r * 1.35), QPointF(cx, cy + r * 1.35))
        # olcu cizgileri
        x = cx + r * 1.5
        p.drawLine(QPointF(x, cy - r), QPointF(x, cy + r))
        for yy in range(int(cy - r), int(cy + r) + 1, 12):
            p.drawLine(QPointF(x - 5, yy), QPointF(x + 5, yy))
        y = cy + r * 1.35
        p.drawLine(QPointF(cx - r, y), QPointF(cx + r, y))
        for xx in (cx - r, cx + r):
            p.drawLine(QPointF(xx, y - 7), QPointF(xx, y + 7))
        p.drawArc(QRectF(cx - r * 1.3, cy - r * 1.3, r * 2.6, r * 2.6), 100 * 16, 70 * 16)
        # yan profil (referanstaki kesit gorunumu)
        px = cx + r * 1.85
        p.setPen(_cos_pen(_rgba(SKETCH, 130), 1))
        for dy in range(-int(r * 0.8), int(r * 0.8) + 1, 14):
            p.drawRect(QRectF(px - 9, cy + dy - 5, 18, 10))
        p.drawLine(QPointF(px - 13, cy - r * 0.9), QPointF(px - 13, cy + r * 0.9))
        f = QFont(p.font())
        f.setPixelSize(15)
        f.setItalic(True)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_rgba(SKETCH, 120))
        p.drawText(QRectF(cx - r * 1.4, cy - r * 1.95, 300, 24), Qt.AlignmentFlag.AlignLeft,
                   "STARK INDUSTRIES")

    def _draw_sketch_rotor(self, p: QPainter) -> None:
        cx, cy = SKETCH_C
        r = SKETCH_R
        spin = self._t * 0.12
        p.setPen(_cos_pen(_rgba(SKETCH, 170), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(10):
            a = spin + i * math.tau / 10
            poly = QPolygonF()
            for rr, da in ((r * 0.5, -0.12), (r * 0.8, -0.16), (r * 0.8, 0.16), (r * 0.5, 0.12)):
                poly.append(QPointF(cx + rr * math.cos(a + da), cy + rr * math.sin(a + da)))
            p.drawPolygon(poly)

    # ---------------------------------------------------------- kadran (sag ust)
    def _dial_angles(self) -> list[float]:
        """Departman isaretlerinin acilari (radyan, ekran koordinati: +y asagi)."""
        n = max(1, len(self._depts))
        if n == 1:
            return [0.0]
        return [-0.95 + i * (1.9 / (n - 1)) for i in range(n)]

    def _draw_dial_static(self, p: QPainter) -> None:
        cx, cy = DIAL_C
        c = QPointF(cx, cy)
        r = DIAL_R
        rect = lambda k: QRectF(cx - r * k, cy - r * k, r * 2 * k, r * 2 * k)  # noqa: E731
        p.setBrush(Qt.BrushStyle.NoBrush)
        # kalin turuncu yay (sol ust ceyrek) + gri yaylar
        pen = _cos_pen(_rgba(DIAL_ORANGE, 220), 1)
        pen.setCosmetic(False)
        pen.setWidthF(14)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawArc(rect(1.0), 95 * 16, 115 * 16)
        pen.setColor(QColor(90, 96, 104, 200))
        p.drawArc(rect(1.0), 210 * 16, 60 * 16)
        pen.setWidthF(9)
        pen.setColor(QColor(120, 128, 138, 170))
        p.setPen(pen)
        p.drawArc(rect(0.74), 60 * 16, 200 * 16)
        p.setPen(_cos_pen(QColor(150, 158, 168, 160), 1))
        p.drawEllipse(c, r * 0.5, r * 0.5)
        p.drawEllipse(c, r * 0.18, r * 0.18)
        p.drawEllipse(c, r * 1.14, r * 1.14)
        # tikler
        for i in range(36):
            a = math.radians(95 + i * 3.2)
            p.drawLine(QPointF(cx + r * 0.84 * math.cos(a), cy - r * 0.84 * math.sin(a)),
                       QPointF(cx + r * 0.92 * math.cos(a), cy - r * 0.92 * math.sin(a)))
        # isaret cizgisi (merkezden saga)
        p.drawLine(QPointF(cx - r * 1.3, cy), QPointF(cx + r * 1.16, cy))
        p.drawEllipse(c, 4, 4)

    def _draw_dial_labels(self, p: QPainter, tr: QTransform) -> None:
        """Isaretler halka uzerinde; etiketler sabit satir araliginda dikey liste (asla cakismaz)."""
        cx, cy = DIAL_C
        s = self._scale()
        self._label_rects = {}
        f = QFont(p.font())
        f.setPixelSize(max(9, int(19 * s)))
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1 if s > 0.45 else 0)
        p.setFont(f)
        fm = p.fontMetrics()
        n = len(self._depts)
        center = tr.map(QPointF(cx, cy))
        row_h = max(fm.height() + 2, DIAL_R * 2.2 * s / max(1, n - 1))
        label_x = center.x() + DIAL_R * 1.32 * s + 8
        for i, (key, a) in enumerate(zip(self._depts, self._dial_angles())):
            count = self.active_count(key)
            hot = count > 0
            sel = key == self._selected or key == self._hover
            ring = tr.map(QPointF(cx + DIAL_R * 1.14 * math.cos(a), cy + DIAL_R * 1.14 * math.sin(a)))
            label_y = center.y() + (i - (n - 1) / 2) * row_h
            color = DIAL_ORANGE if hot else (QColor(theme.ACCENT) if sel else QColor(170, 178, 188))
            pulse = 0.5 + 0.5 * math.sin(self._t * 6) if hot else 1.0
            p.setPen(QPen(_rgba(color, 200), 1.1))
            p.drawLine(ring, QPointF(label_x - 3, label_y))
            p.setBrush(_rgba(color, int(255 * pulse)) if (hot or sel) else Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring, 4.0, 4.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring, 7.0, 7.0)
            text = tr_upper(DIAL_SHORT.get(key, DEPARTMENT_TITLES.get(key, key))) + (f" · {count}" if count else "")
            width = min(fm.horizontalAdvance(text) + 4, max(10.0, self.width() - label_x - 2))
            rect = QRectF(label_x, label_y - fm.height() / 2, width, fm.height())
            p.setPen(_rgba(color if (hot or sel) else QColor(theme.TEXT), 235))
            p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, int(width)))
            self._label_rects[key] = rect

    # ---------------------------------------------------------- guc satiri
    def _draw_power(self, p: QPainter, tr: QTransform) -> None:
        s = self._scale()
        f = QFont(p.font())
        f.setPixelSize(max(10, int(22 * s)))
        f.setBold(False)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        p.setFont(f)
        base = tr.map(QPointF(0, 985))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, base.y() - 12, self.width(), 24), Qt.AlignmentFlag.AlignCenter, self.power_text())
