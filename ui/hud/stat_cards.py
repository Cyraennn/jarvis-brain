"""HUD veri kartlari: saat + takvim + hava, sistem olcumleri, okul ozeti, rutinler, hizli komutlar.

Ag isi (hava durumu) QThreadPool'da calisir, sonuc sinyalle GUI thread'ine doner.
CPU/RAM Windows API'sinden ctypes ile okunur (ek bagimlilik yok); baska platformda "—".
"""

from __future__ import annotations

import calendar
import ctypes
import re
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ui import theme
from ui.hud.hud_card import HudCard

MONTHS_TR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
             "Eylül", "Ekim", "Kasım", "Aralık")
DAYS_TR = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
# tools/quick_tools.py ASCII durum metinleri -> gorunen Turkce
_WEATHER_TR = {
    "acik": "açık", "az bulutlu": "az bulutlu", "parcali bulutlu": "parçalı bulutlu",
    "kapali": "kapalı", "sisli": "sisli", "kirragi sis": "kırağılı sis", "cisenti": "çiseleme",
    "yagmurlu": "yağmurlu", "kuvvetli yagmur": "kuvvetli yağmur", "karli": "karlı",
    "yogun kar": "yoğun kar", "saganak": "sağanak", "gok gurultulu": "gök gürültülü",
    "dolulu firtina": "dolulu fırtına",
}
WEATHER_REFRESH_MS = 15 * 60 * 1000
DAY_INITIALS_TR = ("P", "S", "Ç", "P", "C", "C", "P")
# Hizli komut dosemeleri: (gorunen ad, canli oturuma gonderilen komut)
QUICK_COMMANDS = (
    ("Günlük brifing", "Günlük brifing ver: önemli mailler, bugünün havası ve bekleyen hatırlatıcılar."),
    ("Mailleri özetle", "Gelen kutumdaki okunmamış önemli mailleri özetle."),
    ("Bugünkü program", "Bugünkü ders programımı ve yaklaşan sınavlarımı söyle."),
    ("Sistem durumu", "Bilgisayarın sistem durumunu özetle."),
)
ROUTINE_ROWS_MAX = 6


def _label(text: str, name: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(name)
    return lbl


# ====================================================================== saat
class _WeatherTask(QRunnable):
    def __init__(self, fn: Callable[[str], dict], location: str, done: Callable[[dict], None]) -> None:
        super().__init__()
        self._fn, self._location, self._done = fn, location, done

    def run(self) -> None:
        try:
            result = self._fn(self._location)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
        try:
            self._done(result)
        except RuntimeError:
            pass   # kart bu arada yok edildi


class ClockCard(HudCard):
    weather_ready = Signal(dict)

    def __init__(self, location: str = "", weather_fn: Callable[[str], dict] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__("ŞİMDİ", parent=parent)
        self._location = (location or "").strip()
        self._weather_fn = weather_fn

        row = QHBoxLayout()
        row.setSpacing(0)
        self.time_label = _label("--:--", "hudBig")
        self.sec_label = _label("--", "hudBigSub")
        row.addWidget(self.time_label)
        row.addWidget(_label(":", "hudBig"))
        row.addWidget(self.sec_label)
        row.addStretch(1)
        self.body.addLayout(row)
        self.date_label = _label("", "hudLine")
        self.body.addWidget(self.date_label)
        self.calendar = MiniCalendar()
        self.body.addWidget(self.calendar)
        self.weather_label = _label("", "hudLineStrong")
        self.weather_label.setWordWrap(True)
        self.body.addWidget(self.weather_label)

        self.weather_ready.connect(self._on_weather)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self.tick)
        self._clock.start()
        self.tick()

        self._weather_timer = QTimer(self)
        self._weather_timer.setInterval(WEATHER_REFRESH_MS)
        self._weather_timer.timeout.connect(self.refresh_weather)
        if self._location:
            self.weather_label.setText(f"{self._location} · hava yükleniyor…")
            self._weather_timer.start()
            QTimer.singleShot(800, self.refresh_weather)
        else:
            self.weather_label.hide()

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        self.time_label.setText(now.strftime("%H:%M"))
        self.sec_label.setText(now.strftime("%S"))
        self.date_label.setText(f"{now.day} {MONTHS_TR[now.month - 1]} {now.year} · {DAYS_TR[now.weekday()]}")
        if self.calendar.today != now.date():
            self.calendar.set_date(now.date())

    def refresh_weather(self) -> None:
        if not self._location:
            return
        fn = self._weather_fn
        if fn is None:
            from tools.quick_tools import get_weather
            fn = get_weather
        QThreadPool.globalInstance().start(_WeatherTask(fn, self._location, self.weather_ready.emit))

    def _on_weather(self, data: dict) -> None:
        self.weather_label.setText(format_weather(data, self._location))


class MiniCalendar(QWidget):
    """Ay izgarasi (Pazartesi baslar); bugun vurgu rengiyle dolu kare."""

    HEAD_H = 16
    ROW_H = 19

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.today: date | None = None
        self.weeks: list[list[int]] = []
        self.set_date(date.today())

    def set_date(self, today: date) -> None:
        self.today = today
        self.weeks = calendar.monthcalendar(today.year, today.month)
        self.setFixedHeight(self.HEAD_H + self.ROW_H * len(self.weeks))
        self.update()

    def today_cell(self) -> tuple[int, int]:
        """Bugunun (satir, sutun) konumu."""
        for r, week in enumerate(self.weeks):
            if self.today.day in week:
                return r, week.index(self.today.day)
        return 0, 0

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, self.HEAD_H + self.ROW_H * len(self.weeks))

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cw = self.width() / 7.0
        f = p.font()
        f.setPointSize(7)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_FAINT))
        for c, ch in enumerate(DAY_INITIALS_TR):
            p.drawText(QRectF(c * cw, 0, cw, self.HEAD_H), Qt.AlignmentFlag.AlignCenter, ch)
        cell, ink = QColor(theme.BG_INPUT), QColor(theme.ACCENT_INK)
        accent, dim = QColor(theme.ACCENT), QColor(theme.TEXT_DIM)
        today = self.today_cell()
        for r, week in enumerate(self.weeks):
            for c, day in enumerate(week):
                if not day:
                    continue
                rect = QRectF(c * cw + 1, self.HEAD_H + r * self.ROW_H + 1, cw - 2, self.ROW_H - 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent if (r, c) == today else cell)
                p.drawRoundedRect(rect, 2, 2)
                p.setPen(ink if (r, c) == today else dim)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(day))
        p.end()


def format_weather(data: dict[str, Any], location: str = "") -> str:
    if not data or data.get("error"):
        return f"{location} · hava alınamadı"
    now = data.get("simdi") or {}
    place = str(data.get("konum", location)).split(",")[0]
    temp = now.get("sicaklik")
    durum = _WEATHER_TR.get(str(now.get("durum", "")), str(now.get("durum", "")))
    t = f"{round(temp)}°" if isinstance(temp, (int, float)) else "?°"
    extra = ""
    days = data.get("tahmin") or []
    if days and isinstance(days[0].get("min"), (int, float)):
        extra = f"  ({round(days[0]['min'])}°/{round(days[0]['max'])}°)"
    return f"{place} · {t} {durum}{extra}"


# ==================================================================== sistem
class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

    def value(self) -> int:
        return (self.hi << 32) | self.lo


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class SystemProbe:
    """CPU (iki okuma arasi fark), RAM ve disk doluluk yuzdeleri; okunamazsa None."""

    def __init__(self) -> None:
        self._last: tuple[int, int, int] | None = None

    def cpu(self) -> float | None:
        if sys.platform != "win32":
            return None
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return None
        cur = (idle.value(), kern.value(), user.value())
        prev, self._last = self._last, cur
        if prev is None:
            return None
        d_idle, d_kern, d_user = (cur[i] - prev[i] for i in range(3))
        total = d_kern + d_user           # kernel suresi idle'i da icerir
        if total <= 0:
            return None
        return max(0.0, min(100.0, (total - d_idle) * 100.0 / total))

    @staticmethod
    def ram() -> float | None:
        if sys.platform != "win32":
            return None
        st = _MEMSTATUS()
        st.dwLength = ctypes.sizeof(_MEMSTATUS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return float(st.dwMemoryLoad)

    @staticmethod
    def disk() -> float | None:
        try:
            usage = shutil.disk_usage(Path.home().anchor or "/")
        except OSError:
            return None
        return usage.used * 100.0 / usage.total if usage.total else None


class MeterBar(QWidget):
    """Etiket solda, yuzde sagda, altinda ince cubuk. Yuksek degerde altina, kritikte kirmiziya doner."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.value: float | None = None
        self.setMinimumHeight(26)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 26)

    def set_value(self, value: float | None) -> None:
        self.value = value
        self.update()

    def bar_color(self) -> str:
        if self.value is not None and self.value >= 90:
            return theme.BAD
        if self.value is not None and self.value >= 70:
            return theme.GOLD
        return theme.ACCENT

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        f = p.font()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, 0, w / 2, h - 7), Qt.AlignmentFlag.AlignVCenter, self.label)
        val_txt = "—" if self.value is None else f"%{self.value:.0f}"
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(w / 2, 0, w / 2, h - 7),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, val_txt)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(QRectF(0, h - 5, w, 2.5), 1.2, 1.2)
        if self.value:
            p.setBrush(QColor(self.bar_color()))
            p.drawRoundedRect(QRectF(0, h - 5, max(3.0, w * min(100.0, self.value) / 100.0), 2.5), 1.2, 1.2)
        p.end()


class SystemCard(HudCard):
    INTERVAL_MS = 2000

    def __init__(self, model_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__("SİSTEM", parent=parent)
        self._probe = SystemProbe()
        self._started = time.monotonic()
        self.cpu_bar = MeterBar("CPU")
        self.ram_bar = MeterBar("RAM")
        self.disk_bar = MeterBar("DİSK")
        for bar in (self.cpu_bar, self.ram_bar, self.disk_bar):
            self.body.addWidget(bar)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.addWidget(_label("MODEL", "hudKey"), 0, 0)
        self.model_label = _label(model_name or "?", "hudLine")
        self.model_label.setToolTip(model_name)
        grid.addWidget(self.model_label, 0, 1)
        grid.addWidget(_label("OTURUM", "hudKey"), 1, 0)
        self.uptime_label = _label("00:00:00", "hudLine")
        grid.addWidget(self.uptime_label, 1, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)

        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._probe.cpu()          # ilk okuma: CPU farki icin taban
        self.refresh()

    def refresh(self) -> None:
        self.cpu_bar.set_value(self._probe.cpu())
        self.ram_bar.set_value(self._probe.ram())
        self.disk_bar.set_value(self._probe.disk())
        s = int(time.monotonic() - self._started)
        self.uptime_label.setText(f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")


# ====================================================================== okul
class OkulCard(HudCard):
    INTERVAL_MS = 60_000

    def __init__(self, status_fn: Callable[[], dict] | None = None, parent: QWidget | None = None) -> None:
        super().__init__("OKUL", collapsible=True, parent=parent)
        self._status_fn = status_fn
        self.lines: list[QLabel] = []
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        for row, key in enumerate(("SINAV", "ÖDEV", "BUGÜN")):
            grid.addWidget(_label(key, "hudKey"), row, 0, Qt.AlignmentFlag.AlignTop)
            val = _label("—", "hudLine")
            val.setWordWrap(True)
            grid.addWidget(val, row, 1)
            self.lines.append(val)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        fn = self._status_fn
        if fn is None:
            from tools.okul_tool import okul_status
            fn = okul_status
        try:
            data = fn() or {}
        except Exception as exc:  # noqa: BLE001
            data = {"error": str(exc)}
        for lbl, text in zip(self.lines, summarize_okul(data)):
            lbl.setText(text)
        self.set_meta("bağlı değil" if data.get("error") else "")


def summarize_okul(data: dict[str, Any]) -> tuple[str, str, str]:
    if not data or data.get("error"):
        return ("okul uygulaması bağlı değil", "—", "localhost:8000 açılınca senkronlanır")
    exams = data.get("yaklasan_sinavlar") or []
    if exams:
        e = exams[0]
        days = e.get("kalan_gun")
        when = "bugün" if days == 0 else "yarın" if days == 1 else f"{days} gün"
        exam = f"{e.get('ders', '?')} · {when}" + (f"  (+{len(exams) - 1})" if len(exams) > 1 else "")
    else:
        exam = "14 gün içinde sınav yok"
    late, soon = len(data.get("geciken_odevler") or []), len(data.get("yakin_odevler") or [])
    hw = f"{late} geciken · {soon} bu hafta" if (late or soon) else "bekleyen ödev yok"
    prog = data.get("bugunku_program") or []
    today = f"{len(prog)} ders · ilk {prog[0].get('baslangic', '?')}" if prog else "bugün ders yok"
    return exam, hw, today


# =================================================================== rutinler
def routine_rows(routines: list[dict[str, Any]], reminders: list[dict[str, Any]],
                 now: datetime | None = None) -> list[tuple[str, str, str, bool]]:
    """(saat, ad, durum, vurgulu) satirlari: once bekleyen hatirlaticilar, sonra rutinler."""
    today = (now or datetime.now()).date()
    rows: list[tuple[str, str, str, bool]] = []
    for r in reminders:
        try:
            at = datetime.fromisoformat(str(r.get("fire_at", "")))
            when = at.strftime("%H:%M") if at.date() == today else at.strftime("%d.%m")
        except ValueError:
            when = "—"
        rows.append((when, str(r.get("text", "?")), "BEKLİYOR", True))
    for r in routines:
        m = re.search(r"\d{1,2}:\d{2}", str(r.get("schedule", "")))
        on = bool(r.get("enabled", True))
        rows.append((m.group(0) if m else "—", str(r.get("name", "?")), "AÇIK" if on else "KAPALI", on))
    return rows[:ROUTINE_ROWS_MAX]


def _fetch_schedule() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from tools.scheduler_tools import list_reminders, list_routines

    return list_routines().get("routines", []), list_reminders().get("reminders", [])


class RoutinesCard(HudCard):
    INTERVAL_MS = 60_000

    def __init__(self, fetch_fn: Callable[[], tuple[list, list]] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__("RUTİNLER", collapsible=True, parent=parent)
        self._fetch_fn = fetch_fn or _fetch_schedule
        self.rows: list[tuple[str, str, str, bool]] = []
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(5)
        self._grid.setColumnStretch(1, 1)
        self.body.addLayout(self._grid)
        self.empty_label = _label("tanımlı rutin yok", "hudLine")
        self.body.addWidget(self.empty_label)
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        try:
            routines, reminders = self._fetch_fn()
        except Exception:  # noqa: BLE001 - veri dosyasi yok/bozuk: kart bos kalir
            routines, reminders = [], []
        self.rows = routine_rows(routines, reminders)
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, (when, name, state, on) in enumerate(self.rows):
            self._grid.addWidget(_label(when, "routineTime"), i, 0)
            lbl = _label(name, "routineName")
            lbl.setToolTip(name)
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # dar kartta kirpilir
            self._grid.addWidget(lbl, i, 1)
            self._grid.addWidget(_label(state, "routineStateOn" if on else "routineState"), i, 2)
        self.empty_label.setVisible(not self.rows)
        self.set_meta(f"{len(self.rows)} kayıt" if self.rows else "")


# ============================================================== hizli komutlar
class QuickCommandsCard(HudCard):
    """2x2 hazir komut dosemesi; tiklaninca komut metnini `command` sinyaliyle yayar."""

    command = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("HIZLI KOMUTLAR", parent=parent)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles: list[QPushButton] = []
        for i, (title, prompt) in enumerate(QUICK_COMMANDS):
            tile = QPushButton(f"▶ {title}")
            tile.setObjectName("quickTile")
            tile.setToolTip(prompt)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            tile.clicked.connect(lambda _=False, text=prompt: self.command.emit(text))
            grid.addWidget(tile, i // 2, i % 2)
            self.tiles.append(tile)
        self.body.addLayout(grid)
