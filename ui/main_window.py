"""JARVIS ana penceresi - Obsidian esintili brain-map arayuzu.

Sol ikon serit | sol panel (ajanlar + gorev akisi) | merkez (beyin haritasi +
transkript) | sag panel (canli gorus + sistem gunlugu) | durum cubugu.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.settings import ASSETS_DIR, Settings
from core import personas
from core.webcam_streamer import WebcamStreamer
from ui import theme
from ui.strings import tr_lower
from ui.engine_worker import EngineWorker
from ui.qt_observer import QtEngineObserver
from ui.widgets.agent_panel import AgentPanel
from ui.widgets.brain_graph import BrainGraph
from ui.widgets.content_panel import ContentPanel
from ui.widgets.log_view import LogView
from ui.widgets.transcript_view import TranscriptView
from ui.widgets.webcam_view import WebcamView

_CONN_TEXT = {
    "connecting": ("BAĞLANIYOR", theme.WARN),
    "active": ("BAĞLI", theme.GOOD),
    "reconnecting": ("YENİDEN BAĞLANIYOR", theme.WARN),
    "closed": ("BAĞLANTI YOK", theme.BAD),
    "no-audio": ("SES YOK (mikrofon meşgul)", theme.WARN),
    "offline": ("ÇEVRİMDIŞI · yerel model", theme.WARN),
    "offline-voice": ("ÇEVRİMDIŞI · sesli yerel model", theme.WARN),
}
def _state_text(state: str) -> tuple[str, str]:
    """Durum yazisi + rengi; renk kisilik paletinden o an okunur (bkz. theme.apply_palette)."""
    table = {
        "idle": ("HAZIR", theme.STATE_IDLE),
        "listening": ("DİNLİYOR", theme.ACCENT),
        "speaking": ("KONUŞUYOR", theme.SPEAK),
    }
    return table.get(state, (state.upper(), theme.TEXT_DIM))
_TASK_TERMINAL = {"done", "failed", "blocked", "cancelled"}

_STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "JARVIS"


def _load_app_icon() -> QIcon:
    for name in ("jarvis.ico", "jarvis.png"):
        candidate = ASSETS_DIR / name
        if candidate.is_file():
            icon = QIcon(str(candidate))
            if not icon.isNull():
                return icon
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    accent = QColor(theme.ACCENT)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.BG_DEEP))
    p.drawEllipse(2, 2, 60, 60)
    p.setPen(QPen(accent, 4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(12, 12, 40, 40))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(accent)
    p.drawEllipse(QRectF(26, 26, 12, 12))
    p.end()
    return QIcon(pm)


_tr_lower = tr_lower   # geriye uyumluluk (testler bu adi kullaniyor)


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MainWindow(QMainWindow):
    log_message = Signal(str, str)
    # Telefon konsolundan (web thread'i) gelen uyandirma kelimesi ac/kapa -> Qt thread'inde uygulanir
    wake_toggle_requested = Signal(bool)

    def __init__(
        self,
        settings: Settings,
        observer: QtEngineObserver,
        webcam: WebcamStreamer,
        orch_observer: object | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._observer = observer
        self._orch_observer = orch_observer
        self._webcam = webcam
        self._worker: EngineWorker | None = None
        self._orch_worker: object | None = None
        self._web_worker: object | None = None
        self._shutting_down = False
        self._force_quitting = False
        self._tray_hint_shown = False

        self._in_level = 0.0
        self._out_level = 0.0
        self._task_count = 0
        self._task_status: dict[str, str] = {}   # gorev id -> son durum (aktif/toplam icin)
        self._focus_mode = False
        self._focus_saved: tuple[bool, bool] = (True, True)
        self._agent_count = 0
        self._active_dialog: QMessageBox | None = None
        self._mic_lost = False   # ses cihazi dustu (no-audio) -> mic dugmesi kapali gosterildi
        self._wake_asleep = False  # uyandirma kapisi uykuda ("Hey JARVIS" bekleniyor)

        self._icon = _load_app_icon()
        self.setWindowIcon(self._icon)
        self.setWindowTitle(theme.branding()["name"])
        self._last_state = "idle"
        self.resize(1320, 860)

        self._build_ui()
        self._wire_observer()
        self._build_tray()

        self.log_message.connect(self._log.add_log)
        self.wake_toggle_requested.connect(lambda on: self._wake_btn.setChecked(on))

        if settings.always_on_top:
            self._apply_on_top(True)
        if settings.webcam_enabled:
            self._webcam.start()

    # ------------------------------------------------------------ dis baglanti
    def attach_worker(self, worker: EngineWorker) -> None:
        self._worker = worker

    def attach_orchestrator_worker(self, worker: object) -> None:
        self._orch_worker = worker

    def attach_web_worker(self, worker: object) -> None:
        self._web_worker = worker
        from PySide6.QtCore import QTimer

        def _show_url() -> None:
            url = getattr(worker, "url", "")
            if url:
                self._web_url = url
                self._sb_web.setToolTip(f"Web konsolu: {url}\nTıkla: bağlantıyı kopyala")
                self._sb_web.show()
                self._sb_web_sep.show()
                self._log.add_event("\U0001f4f1", f"Web konsolu: {url}", theme.ACCENT)
        QTimer.singleShot(1500, _show_url)

    # ================================================================= UI
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_ribbon())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_sidebar())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right_sidebar())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([250, 720, 300])
        self._splitter = splitter
        body.addWidget(splitter, 1)

        outer.addLayout(body, 1)
        outer.addWidget(self._build_statusbar())
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._close_panel)

    # ----------------------------------------------------------- icerik paneli
    def _mount_panel(self, graph: QWidget) -> QStackedWidget:
        """Merkez gorseli (beyin haritasi / komuta grafi) ile icerik panelini ayni yere koyar;
        video, Wikipedia, belge, site ve Spotify karti gorselin yerinde acilir."""
        stack = QStackedWidget()
        stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        stack.addWidget(graph)
        self._content_panel = ContentPanel()
        self._content_panel.closed.connect(self._close_panel)
        stack.addWidget(self._content_panel)
        self._center_stack = stack
        return stack

    def _panel_open(self) -> bool:
        return self._center_stack.currentWidget() is self._content_panel

    def _on_panel(self, payload: dict) -> None:
        if payload.get("kind") == "close":
            self._close_panel()
            return
        if payload.get("kind") == "map_control":
            # Harita aciksa kamera komutu; degilse once Izmir haritasi acilir
            if self._panel_open() and self._content_panel.map_command(str(payload.get("action", ""))):
                return
            if self._panel_open() and self._content_panel.kind == "map":
                return   # harita henuz yukleniyor
            from tools.panel_tools import show_map

            payload = show_map("")["panel"]
        title = _elide(str(payload.get("title", "")), 60)
        if not self._content_panel.show_content(payload):
            self._close_panel()
            self._log.add_event("↗", f"Panel açılamadı, tarayıcıda açıldı: {title}", theme.WARN)
            return
        self._center_stack.setCurrentWidget(self._content_panel)
        self._graph.set_active(False)   # gorunmeyen animasyon bosuna CPU yakmasin
        self._log.add_event("▣", f"Panel: {title}", theme.ACCENT)

    def _close_panel(self) -> bool:
        """Icerik panelini kapatip merkez gorsele doner. Panel acik degilse False."""
        if not self._panel_open():
            return False
        self._content_panel.clear()
        self._center_stack.setCurrentWidget(self._graph)
        self._graph.set_active(not self.isMinimized())
        return True

    # ----------------------------------------------------------------- ribbon
    def _ribbon_btn(self, glyph: str, tip: str, *, checkable: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("ribbonBtn")
        btn.setText(glyph)
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _build_ribbon(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ribbon")
        frame.setFixedWidth(46)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(5, 10, 5, 10)
        lay.setSpacing(4)

        home = self._ribbon_btn("\U0001f9e0", "Odak modu: yan panelleri gizle / göster", checkable=True)
        home.toggled.connect(self._toggle_focus_mode)
        self._home_btn = home
        lay.addWidget(home)
        lay.addSpacing(8)

        self._mic_btn = self._ribbon_btn("\U0001f3a4", "Mikrofon (aç/kapa)", checkable=True)
        self._mic_btn.setChecked(True)
        self._mic_btn.toggled.connect(self._on_mic_toggled)
        lay.addWidget(self._mic_btn)

        self._wake_btn = self._ribbon_btn(
            "\U0001f442", f"Uyandırma kelimesi: yalnızca '{self._settings.wake_phrase}' deyince dinle",
            checkable=True)
        self._wake_btn.setChecked(self._settings.wake_word_enabled)
        self._wake_btn.toggled.connect(self._on_wake_toggled)
        lay.addWidget(self._wake_btn)

        self._cam_btn = self._ribbon_btn("\U0001f4f7", "Kamera (aç/kapa)", checkable=True)
        self._cam_btn.setChecked(self._settings.webcam_enabled)
        self._cam_btn.toggled.connect(self._on_cam_toggled)
        lay.addWidget(self._cam_btn)

        self._screen_btn = self._ribbon_btn("\U0001f5a5", "Ekran görüşü (aç/kapa)", checkable=True)
        self._screen_btn.setChecked(self._settings.screen_enabled)
        self._screen_btn.toggled.connect(self._on_screen_toggled)
        lay.addWidget(self._screen_btn)

        self._hud_btn = self._ribbon_btn("\U0001f590", "Jest HUD (3D kontrol)")
        self._hud_btn.clicked.connect(self._open_gesture_hud)
        lay.addWidget(self._hud_btn)

        self._pipe_btn = self._ribbon_btn("\U0001f4c8", "Decision Pipeline (router kararları)")
        self._pipe_btn.clicked.connect(self._open_decision_pipeline)
        lay.addWidget(self._pipe_btn)

        self._team_btn = self._ribbon_btn("\U0001f9be", "Stark Ekibi (aç/kapa)", checkable=True)
        self._team_btn.toggled.connect(self._toggle_stark_team)
        lay.addWidget(self._team_btn)

        lay.addSpacing(8)
        self._left_btn = self._ribbon_btn("\U0001f5c2", "Sol paneli göster/gizle", checkable=True)
        self._left_btn.setChecked(True)
        self._left_btn.toggled.connect(lambda v: self._toggle_panel("left", v))
        lay.addWidget(self._left_btn)
        self._right_btn = self._ribbon_btn("\U0001f4ca", "Sağ paneli göster/gizle", checkable=True)
        self._right_btn.setChecked(True)
        self._right_btn.toggled.connect(lambda v: self._toggle_panel("right", v))
        lay.addWidget(self._right_btn)

        self._top_btn = self._ribbon_btn("\U0001f4cc", "Her zaman üstte", checkable=True)
        self._top_btn.setChecked(self._settings.always_on_top)
        self._top_btn.toggled.connect(self._apply_on_top)
        lay.addWidget(self._top_btn)

        lay.addStretch(1)
        self._tray_btn = self._ribbon_btn("\U0001f53d", "Tepsiye küçült")
        self._tray_btn.clicked.connect(self._hide_to_tray)
        lay.addWidget(self._tray_btn)
        self._stop_btn = self._ribbon_btn("⏻", "Çıkış")
        self._stop_btn.clicked.connect(self._force_quit)
        lay.addWidget(self._stop_btn)
        return frame

    # ----------------------------------------------------------- left sidebar
    def _build_left_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setProperty("class", "sidebarLeft")
        frame.setStyleSheet(f"QFrame#sidebar {{ border-right: 1px solid {theme.BORDER}; }}")
        frame.setMinimumWidth(200)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(4)

        brand = QLabel("C Y R A E N")
        brand.setObjectName("title")
        brand.setContentsMargins(8, 4, 8, 0)
        sub = QLabel("BRAIN MAP  ·  GEMINI LIVE")
        sub.setObjectName("subtitle")
        sub.setContentsMargins(8, 0, 8, 6)
        lay.addWidget(brand)
        lay.addWidget(sub)

        self._agent_panel = AgentPanel()
        self._agent_panel.agent_selected.connect(self._on_agent_selected)
        lay.addWidget(self._agent_panel, 1)
        self._left_sidebar = frame
        return frame

    # --------------------------------------------------------------- center
    def _build_center(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        tabbar = QFrame()
        tabbar.setObjectName("tabbar")
        tb = QHBoxLayout(tabbar)
        tb.setContentsMargins(0, 0, 8, 0)
        tb.setSpacing(0)
        tab = QLabel("◈  BEYİN HARİTASI")
        tab.setObjectName("sectionLabel")
        tab.setContentsMargins(16, 9, 0, 9)
        tb.addWidget(tab)
        tb.addStretch(1)
        self._conn_pill = QLabel("●  BAĞLANIYOR")
        self._conn_pill.setObjectName("statusItem")
        self._set_conn(self._conn_pill, "BAĞLANIYOR", theme.WARN)
        tb.addWidget(self._conn_pill)
        v.addWidget(tabbar)

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setHandleWidth(1)
        vsplit.setChildrenCollapsible(False)

        graph_area = QWidget()
        ga = QVBoxLayout(graph_area)
        ga.setContentsMargins(16, 14, 16, 8)
        ga.setSpacing(6)
        self._graph = BrainGraph()
        self._graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._graph.node_clicked.connect(self._on_agent_selected)   # ajan adi ya da "dept:<key>"
        ga.addWidget(self._mount_panel(self._graph), 1)
        self._state_line = QLabel("HAZIR")
        self._state_line.setObjectName("stateLine")
        self._state_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_line.setStyleSheet(f"color:{theme.STATE_IDLE};")
        ga.addWidget(self._state_line)
        self._caption = QLabel("")
        self._caption.setObjectName("caption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        self._caption.setMinimumHeight(38)
        ga.addWidget(self._caption)
        vsplit.addWidget(graph_area)

        tr_area = QWidget()
        ta = QVBoxLayout(tr_area)
        ta.setContentsMargins(12, 6, 12, 10)
        ta.setSpacing(6)
        tr_lbl = QLabel("KONUŞMA")
        tr_lbl.setObjectName("sectionLabel")
        ta.addWidget(tr_lbl)
        self._transcript = TranscriptView()
        ta.addWidget(self._transcript, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._bridge_input = QLineEdit()
        self._bridge_input.setPlaceholderText("Köprü mesajı / komut  —  Enter ile canlı oturuma enjekte et")
        self._bridge_input.returnPressed.connect(self._on_bridge_send)
        row.addWidget(self._bridge_input, 1)
        send = QPushButton("GÖNDER")
        send.clicked.connect(self._on_bridge_send)
        row.addWidget(send)
        ta.addLayout(row)
        vsplit.addWidget(tr_area)

        vsplit.setSizes([520, 300])
        v.addWidget(vsplit, 1)
        return wrap

    # ---------------------------------------------------------- right sidebar
    def _build_right_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setStyleSheet(f"QFrame#sidebar {{ border-left: 1px solid {theme.BORDER}; }}")
        frame.setMinimumWidth(240)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(self._nav_header("CANLI GÖRÜŞ"))
        self._webcam_view = WebcamView(self._webcam.get_latest_jpeg, placeholder="KAMERA KAPALI")
        self._webcam_view.setMinimumHeight(150)
        self._webcam_view.set_active(self._settings.webcam_enabled)
        lay.addWidget(self._webcam_view)

        self._screen_view = WebcamView(self._screen_frame, placeholder="EKRAN KAPALI")
        self._screen_view.setMinimumHeight(150)
        self._screen_view.set_active(self._settings.screen_enabled)
        lay.addWidget(self._screen_view)

        lay.addWidget(self._nav_header("SİSTEM GÜNLÜĞÜ"))
        self._log = LogView()
        lay.addWidget(self._log, 1)
        self._right_sidebar = frame
        return frame

    def _nav_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("navHeader")
        return lbl

    def _screen_frame(self):  # noqa: ANN202
        worker = self._worker
        engine = getattr(worker, "engine", None) if worker else None
        screen = getattr(engine, "screen", None)
        if screen is None:
            return None
        try:
            return screen.get_latest_jpeg()
        except Exception:  # noqa: BLE001
            return None

    # -------------------------------------------------------------- statusbar
    def _build_statusbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(26)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(0)

        self._sb_conn = self._status_item("● bağlanıyor")
        model_name = str(getattr(self._settings, "model", "") or "").removeprefix("models/").removesuffix("-latest")
        self._sb_model = self._status_item(_elide(model_name, 34) or "model ?")
        self._sb_model.setToolTip(f"Canlı ses modeli: {model_name}")
        self._sb_io = self._status_item("mic ●  cam ●  ekran ●")
        self._sb_agents = self._status_item("0 ajan")
        self._sb_tasks = self._status_item("GÖREV 0/0")
        self._sb_tasks.setToolTip("Aktif / toplam ajan görevi")
        for i, w in enumerate((self._sb_conn, self._sb_model, self._sb_io, self._sb_agents)):
            lay.addWidget(w)
            sep = QLabel("│")
            sep.setObjectName("statusSep")
            lay.addWidget(sep)
        lay.addWidget(self._sb_tasks)
        self._sb_web_sep = QLabel("│")
        self._sb_web_sep.setObjectName("statusSep")
        self._sb_web = self._status_item("\U0001f4f1 web")
        self._sb_web.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sb_web.mousePressEvent = lambda _e: self._copy_web_url()  # noqa: ANN001
        self._web_url = ""
        for w in (self._sb_web_sep, self._sb_web):
            w.hide()
            lay.addWidget(w)
        lay.addStretch(1)
        hint = QLabel("beyin haritası · ajanlar JARVIS'e bağlı")
        hint.setObjectName("statusItem")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # dar pencerede kirpilir
        lay.addWidget(hint)
        self._update_io_status()   # baslangic metni gercek ayarlari yansitsin
        return bar

    def _copy_web_url(self) -> None:
        if not self._web_url:
            return
        QApplication.clipboard().setText(self._web_url)
        self._log.add_event("\U0001f4cb", "Web konsolu bağlantısı panoya kopyalandı.", theme.TEXT_DIM)

    def _status_item(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("statusItem")
        return lbl

    # ================================================================= observer
    def _wire_observer(self) -> None:
        o = self._observer
        o.connection.connect(self._on_connection)
        o.state.connect(self._on_state)
        o.input_level.connect(self._on_input_level)
        o.output_level.connect(self._on_output_level)
        o.user_transcript.connect(self._on_user_transcript)
        o.assistant_transcript.connect(self._on_assistant_transcript)
        o.tool_call.connect(self._on_tool_call)
        o.tool_result.connect(self._on_tool_result)
        o.bridge_message.connect(self._on_bridge_message)
        o.confirm_requested.connect(self._on_confirm_requested)
        o.app_exit_requested.connect(self._on_exit_requested)
        o.external_typing.connect(self._on_external_typing)
        o.panel.connect(self._on_panel)
        o.wake.connect(self._on_wake)
        o.persona.connect(self._on_persona)

        if self._orch_observer is not None:
            self._orch_observer.agents_loaded.connect(self._on_agents_loaded)
            self._orch_observer.task.connect(self._on_orch_task)
            appr = getattr(self._orch_observer, "approval_requested", None)
            if appr is not None:
                appr.connect(self._on_approval_requested)

    def _on_persona(self, key: str) -> None:
        mode = personas.get(self._settings, key)
        self.apply_persona_theme(mode.key)
        self._log.add_event("◆", f"{mode.name} devrede — yeni kişilikle bağlanılıyor", mode.color)

    def apply_persona_theme(self, key: str) -> str:
        """Kisilik paletini uygular: global QSS + `refresh_theme()` olan her widget + baslik.

        HudWindow metinleri, orb'u ve efekt katmanini ekler. Uygulanan anahtari doner.
        """
        key = theme.apply_palette(key)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.QSS)
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_theme", None)
            if callable(refresh):
                refresh()
        name = theme.branding(key)["name"]
        if app is not None:
            app.setApplicationDisplayName(name)   # Windows baslik/gorev cubugu adi
        self.setWindowTitle(name)
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.setToolTip(name)
        return key

    def _on_connection(self, status: str) -> None:
        text, color = _CONN_TEXT.get(status, (status.upper(), theme.TEXT_DIM))
        self._set_conn(self._conn_pill, text, color)
        self._sb_conn.setText(f"● {_tr_lower(text)}")
        self._sb_conn.setStyleSheet(f"color:{color};")
        self._log.add_event("●", f"Bağlantı: {text}", color)
        self._sync_mic_with_audio(status)

    def _sync_mic_with_audio(self, status: str) -> None:
        """Ses cihazi dusunce mic dugmesi 'acik' gorunmesin; ses geri gelince eski haline don."""
        if status == "no-audio" and self._mic_btn.isChecked():
            self._mic_lost = True
            self._set_checked_silently(self._mic_btn, False)
            self._mic_btn.setToolTip("Ses cihazı meşgul — yeniden denemek için tıkla")
        elif status == "active" and self._mic_lost:
            self._mic_lost = False
            self._set_checked_silently(self._mic_btn, True)
            self._mic_btn.setToolTip("Mikrofon (aç/kapa)")
        else:
            return
        self._update_io_status()

    @staticmethod
    def _set_checked_silently(btn: QToolButton, on: bool) -> None:
        btn.blockSignals(True)
        btn.setChecked(on)
        btn.blockSignals(False)

    def _on_wake(self, awake: bool) -> None:
        was_asleep = self._wake_asleep
        self._wake_asleep = not awake
        if awake and was_asleep and self._wake_btn.isChecked():
            from ui.sound import play_chime

            play_chime()
            self._log.add_event("◉", "Uyandırma kelimesi algılandı", theme.ACCENT)
        self._on_state("listening" if awake and was_asleep else "idle")

    def _on_wake_toggled(self, checked: bool) -> None:
        self._log.add_event(
            "◉", "Uyandırma kelimesi " + (f"AÇIK — '{self._settings.wake_phrase}' deyin" if checked else "kapalı"),
            theme.ACCENT)
        if not checked:
            self._wake_asleep = False
            self._on_state("idle")
        if self._worker is not None:
            self._worker.set_wake_word_enabled(checked)
        from web.event_bus import BUS

        BUS.push("control_state", {"wake": checked})  # telefon konsolu dugmesi senkron kalsin

    def _on_state(self, state: str) -> None:
        self._last_state = state
        text, color = _state_text(state)
        if state == "idle" and self._wake_asleep:
            text, color = f"UYKUDA · '{self._settings.wake_phrase}'", theme.TEXT_DIM
        self._state_line.setText(text)
        self._state_line.setStyleSheet(f"color:{color};")
        self._graph.set_center_mode(state)
        if state != "listening":
            self._caption.setText("")

    def _on_input_level(self, level: float) -> None:
        self._in_level = level
        self._graph.set_center_level(max(self._in_level, self._out_level))

    def _on_output_level(self, level: float) -> None:
        self._out_level = level
        self._graph.set_center_level(max(self._in_level, self._out_level))

    def _on_user_transcript(self, text: str, final: bool) -> None:
        if final:
            self._transcript.add_user(text)
            self._caption.setText("")
        else:
            self._caption.setText(f"“{text}”")

    def _on_assistant_transcript(self, text: str, final: bool) -> None:
        if final:
            self._transcript.add_assistant(text)
        else:
            self._caption.setText(text)

    def _on_tool_call(self, names: list) -> None:
        self._log.add_event("\U0001f6e0", f"Araç çağrısı: {', '.join(names)}", theme.ACCENT)

    def _on_tool_result(self, name: str, ok: bool, detail: str) -> None:
        icon = "✓" if ok else "✗"
        color = theme.GOOD if ok else theme.BAD
        self._log.add_event(icon, f"{name} -> {detail}", color)

    def _on_bridge_message(self, text: str) -> None:
        self._log.add_event("\U0001f309", f"Köprü: {text}", theme.JARVIS_COLOR)
        self._transcript.add_system(f"Köprü mesajı: {text}")

    # --------------------------------------------------------- orkestrator
    def _on_agents_loaded(self, agents: list) -> None:
        self._agent_panel.set_agents(agents)
        self._graph.set_agents(agents)
        self._agent_count = len(agents)
        depts = {getattr(getattr(a, "department", None), "value", "") for a in agents}
        self._sb_agents.setText(f"{len(depts - {''})} departman · {self._agent_count} ajan")
        self._log.add_event(
            "\U0001f578", f"Ajan ağı: {self._agent_count} ajan / {len(depts - {''})} departman JARVIS'e bağlı", theme.ACCENT
        )

    def _on_orch_task(self, update: object) -> None:
        agent = getattr(update, "agent", "")
        status = getattr(update, "status", "")
        self._graph.set_agent_status(agent, status)
        self._agent_panel.set_agent_status(agent, status)
        self._agent_panel.add_task_update(update)
        tid = str(getattr(update, "id", "") or f"{agent}:{len(self._task_status)}")
        self._task_status[tid] = str(status)
        if len(self._task_status) > 500:      # sinirsiz buyumesin: bitenlerin en eskilerini at
            for k in [k for k, v in self._task_status.items() if v in _TASK_TERMINAL][:100]:
                del self._task_status[k]
        active = sum(1 for v in self._task_status.values() if v not in _TASK_TERMINAL)
        self._task_count = len(self._task_status)
        self._sb_tasks.setText(f"GÖREV {active}/{self._task_count}")
        if status in ("done", "failed", "blocked"):
            icon = {"done": "✓", "failed": "✗", "blocked": "⚿"}[status]
            color = theme.GOOD if status == "done" else theme.BAD
            res = getattr(update, "result", None) or getattr(update, "detail", "")
            self._log.add_event(icon, f"[{agent}] {str(res)[:130]}", color)

    def _on_agent_selected(self, name: str) -> None:
        if name.startswith("dept:"):
            self._agent_panel.expand_department(name.removeprefix("dept:"))
            return
        self._agent_panel.select(name)

    def _on_approval_requested(self, request: object) -> None:
        self._log.add_event("❓", "Ajan onayı isteniyor", theme.WARN)
        self._ask(request, "JARVIS — Ajan Onayı", "Onayla ve çalıştır", "Reddet",
                  ("Ajan onaylandı", "Ajan reddedildi"))

    def _on_confirm_requested(self, request: object) -> None:
        prompt = getattr(request, "prompt", "Onaylıyor musunuz?")
        self._log.add_event("❓", f"Onay isteniyor: {prompt}", theme.WARN)
        self._ask(request, "JARVIS — Onay", "Evet", "Hayır", ("Onay verildi", "Onay reddedildi"))

    def _ask(self, request: object, title: str, yes_text: str, no_text: str,
             messages: tuple[str, str]) -> None:
        """Modal onay diyalogu. Pencere gizliyse one getirir; istek motor tarafinda zaman
        asimina ugrarsa (`request.expired`) diyalog kendini kapatir ve reddedildi sayilir."""
        from PySide6.QtCore import QTimer

        was_hidden = not self.isVisible()
        was_minimized = self.isMinimized()
        if was_hidden or was_minimized:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self._exclude_from_capture()
            if self._tray is not None:
                self._tray.showMessage("JARVIS", "Onayın bekleniyor.", self._icon, 4000)

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(getattr(request, "prompt", "Onaylıyor musunuz?"))
        yes = box.addButton(yes_text, QMessageBox.ButtonRole.YesRole)
        box.addButton(no_text, QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(yes)

        watch = QTimer(box)
        watch.setInterval(300)
        watch.timeout.connect(lambda: getattr(request, "expired", False) and box.reject())
        watch.start()
        self._active_dialog = box   # testler/dis kapatma icin
        try:
            box.exec()
        finally:
            watch.stop()
            self._active_dialog = None

        if getattr(request, "remote_resolved", False):
            self._log.add_event("📱", "Onay başka cihazdan yanıtlandı.", theme.GOOD)
        elif getattr(request, "expired", False):
            self._log.add_event("⌛", "Onay zaman aşımına uğradı — reddedildi.", theme.BAD)
        else:
            approved = box.clickedButton() is yes
            self._log.add_event("✔" if approved else "✖", messages[0] if approved else messages[1],
                                theme.GOOD if approved else theme.BAD)
            resolve = getattr(request, "resolve", None)
            if callable(resolve):
                resolve(approved)

        if was_hidden:
            self._hide_to_tray()
        elif was_minimized:
            self.showMinimized()

    # ================================================================= kontroller
    def _on_mic_toggled(self, checked: bool) -> None:
        if checked and self._mic_lost:
            self._mic_lost = False
            self._mic_btn.setToolTip("Mikrofon (aç/kapa)")
        self._update_io_status()
        if self._worker is not None:
            self._worker.set_mic_muted(not checked)
            if checked:
                self._worker.retry_audio()  # ses cihazi dustuyse geri almayi dene

    def _on_cam_toggled(self, checked: bool) -> None:
        if checked:
            self._webcam.start()
        else:
            self._webcam.stop()
        self._webcam_view.set_active(checked)
        self._update_io_status()
        if self._worker is not None:
            self._worker.set_webcam_streaming(checked)

    def _on_screen_toggled(self, checked: bool) -> None:
        self._screen_view.set_active(checked)
        self._update_io_status()
        self._log.add_event(
            "\U0001f5a5",
            "Ekran görüşü açıldı" if checked else "Ekran görüşü kapatıldı",
            theme.ACCENT if checked else theme.TEXT_DIM,
        )
        if self._worker is not None:
            self._worker.set_screen_streaming(checked)

    def _open_gesture_hud(self) -> None:
        from tools.app_launcher import open_gesture_hud

        result = open_gesture_hud()
        if result.get("error"):
            self._log.add_event("\U0001f590", f"Jest HUD açılamadı: {result['error']}", theme.BAD)
            return
        self._log.add_event(
            "\U0001f590",
            f"Jest HUD açıldı ({result.get('mode', '')}): {result.get('url', '')}",
            theme.ACCENT,
        )

    def _open_decision_pipeline(self) -> None:
        """Router kararlarini canli gosteren Decision Pipeline panosu (Qt WebEngine penceresi)."""
        from ui.dashboard.window import DashboardWindow

        if getattr(self, "_pipe_win", None) is None:
            self._pipe_win = DashboardWindow()
        result = self._pipe_win.open(self._settings)
        if result.get("error"):
            self._log.add_event("\U0001f4c8", f"Decision Pipeline açılamadı: {result['error']}", theme.BAD)
            return
        self._log.add_event("\U0001f4c8", f"Decision Pipeline açıldı: {result.get('url', '')}", theme.ACCENT)

    def _toggle_stark_team(self, on: bool) -> None:
        """Stark Ekibi penceresini ac/kapat; pencere elle kapatilirsa dugme de soner."""
        from PySide6.QtCore import QTimer

        from tools.app_launcher import StarkTeamWindow

        if getattr(self, "_team_win", None) is None:
            self._team_win = StarkTeamWindow()
            self._team_timer = QTimer(self)
            self._team_timer.setInterval(1000)
            self._team_timer.timeout.connect(self._watch_stark_team)
        if not on:
            self._team_timer.stop()
            self._team_win.close()
            self._log.add_event("\U0001f9be", "Stark Ekibi kapatıldı", theme.ACCENT)
            return
        result = self._team_win.open()
        if result.get("error"):
            self._log.add_event("\U0001f9be", f"Stark Ekibi açılamadı: {result['error']}", theme.BAD)
            self._set_checked_silently(self._team_btn, False)
            return
        if not result.get("closable", True):
            # Chrome/Edge yok: normal sekmede acildi, dugmeyle kapatilamaz
            self._log.add_event("\U0001f9be", "Stark Ekibi tarayıcı sekmesinde açıldı", theme.ACCENT)
            self._set_checked_silently(self._team_btn, False)
            return
        self._team_timer.start()
        self._log.add_event("\U0001f9be", "Stark Ekibi açıldı", theme.ACCENT)

    def _watch_stark_team(self) -> None:
        if not self._team_win.is_open():
            self._team_timer.stop()
            self._set_checked_silently(self._team_btn, False)

    def _update_io_status(self) -> None:
        def mark(on: bool) -> str:
            return "●" if on else "○"

        self._sb_io.setText(
            f"mic {mark(self._mic_btn.isChecked())}  "
            f"cam {mark(self._cam_btn.isChecked())}  "
            f"ekran {mark(self._screen_btn.isChecked())}"
        )

    def _on_bridge_send(self) -> None:
        text = self._bridge_input.text().strip()
        if not text or self._worker is None:
            return
        self._worker.inject_bridge_message(text)
        self._transcript.add_system(f"Sen (köprü): {text}")
        self._bridge_input.clear()

    def _toggle_panel(self, side: str, visible: bool) -> None:
        target = self._left_sidebar if side == "left" else self._right_sidebar
        target.setVisible(visible)
        if visible and self._focus_mode:
            # odak modundayken bir panel elle acildi: odak modu artik gecerli degil
            self._focus_mode = False
            self._set_checked_silently(self._home_btn, False)

    def _toggle_focus_mode(self, on: bool) -> None:
        """Beyin haritasina odaklan: iki yan paneli gizle; kapatinca eski haline don."""
        if on == self._focus_mode:
            return
        self._focus_mode = on
        if on:
            self._focus_saved = (self._left_btn.isChecked(), self._right_btn.isChecked())
            self._left_btn.setChecked(False)
            self._right_btn.setChecked(False)
        else:
            self._left_btn.setChecked(self._focus_saved[0])
            self._right_btn.setChecked(self._focus_saved[1])

    # ================================================================= yardimci
    @staticmethod
    def _set_conn(label: QLabel, text: str, color: str) -> None:
        label.setText(f"●  {text}")
        label.setStyleSheet(f"color:{color};font-size:11px;font-weight:600;letter-spacing:1px;")

    # ============================================================ tepsi / ustte
    def _build_tray(self) -> None:
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self._icon, self)
        self._tray.setToolTip(theme.branding()["name"])
        menu = QMenu()
        self._act_visible = menu.addAction("Gizle", self._toggle_visible)
        menu.addSeparator()
        self._act_top = menu.addAction("Her zaman üstte")
        self._act_top.setCheckable(True)
        self._act_top.setChecked(self._settings.always_on_top)
        self._act_top.toggled.connect(self._apply_on_top)
        self._act_startup = menu.addAction("Windows ile başlat")
        self._act_startup.setCheckable(True)
        self._act_startup.setChecked(self._is_run_at_startup())
        self._act_startup.toggled.connect(self._set_run_at_startup)
        menu.addSeparator()
        menu.addAction("Çıkış", self._force_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle_visible()

    def _toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self._hide_to_tray()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            if hasattr(self, "_act_visible"):
                self._act_visible.setText("Gizle")

    def _hide_to_tray(self) -> None:
        if self._tray is None:
            self.showMinimized()
            return
        self.hide()
        if hasattr(self, "_act_visible"):
            self._act_visible.setText("Göster")
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self._tray.showMessage(
                "JARVIS", "Tepside çalışmaya devam ediyor.", self._icon, 4000
            )

    def _exclude_from_capture(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            if not ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011):
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000001)
        except Exception:  # noqa: BLE001
            pass

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        self._exclude_from_capture()

    def changeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            # Kucultulmusken (ya da icerik paneli acikken) beyin haritasi animasyonu bosuna CPU yakmasin
            self._graph.set_active(not self.isMinimized() and not self._panel_open())

    def _apply_on_top(self, on: bool) -> None:
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
            self._exclude_from_capture()
        for widget in (getattr(self, "_top_btn", None), getattr(self, "_act_top", None)):
            if widget is not None and widget.isChecked() != on:
                widget.blockSignals(True)
                widget.setChecked(on)
                widget.blockSignals(False)

    # ---------------------------------------------------- windows ile baslat
    def _is_run_at_startup(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_PATH) as key:
                winreg.QueryValueEx(key, _STARTUP_REG_NAME)
            return True
        except OSError:
            return False

    def _startup_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        pyw = Path(sys.executable).with_name("pythonw.exe")
        runner = Path(__file__).resolve().parent.parent / "run_ui.py"
        exe = pyw if pyw.exists() else Path(sys.executable)
        return f'"{exe}" "{runner}"'

    def _set_run_at_startup(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key, _STARTUP_REG_NAME, 0, winreg.REG_SZ, self._startup_command()
                    )
                else:
                    try:
                        winreg.DeleteValue(key, _STARTUP_REG_NAME)
                    except FileNotFoundError:
                        pass
            self._log.add_event(
                "●",
                "Windows ile başlatma açıldı." if enabled else "Windows ile başlatma kapatıldı.",
                theme.TEXT_DIM,
            )
        except OSError as exc:
            self._log.add_event("✖", f"Başlangıç ayarı değiştirilemedi: {exc}", theme.BAD)

    # ---------------------------------------------------------- dis yazma
    def _on_external_typing(self, active: bool) -> None:
        if active:
            self._was_minimized = self.isMinimized() or not self.isVisible()
            self.showMinimized()
            self._log.add_event("⌨", "Kenara çekiliyorum (yazıyor/tıklıyor)...", theme.TEXT_DIM)
        else:
            if not getattr(self, "_was_minimized", False):
                self.showNormal()
                self.raise_()
                self._exclude_from_capture()
            self._log.add_event("⌨", "İşlem tamam, geri geldim.", theme.TEXT_DIM)

    # ---------------------------------------------------------------- kapatma
    def _on_exit_requested(self) -> None:
        self._log.add_event("●", "JARVIS kendini kapatıyor (araç).", theme.WARN)
        self._force_quit()

    def _force_quit(self) -> None:
        self._force_quitting = True
        self.close()

    def _shutdown_sequence(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._log.add_event("●", "Kapatılıyor...", theme.WARN)
        self._content_panel.clear()   # panelde calan video/ses dursun
        for name in ("_mic_btn", "_wake_btn", "_cam_btn", "_screen_btn", "_stop_btn", "_tray_btn",
                     "_top_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(False)
        if self._tray is not None:
            self._tray.hide()
        if getattr(self, "_team_win", None) is not None:
            self._team_win.close()
        if self._worker is not None:
            self._worker.shutdown()
        orch = self._orch_worker
        if orch is not None and hasattr(orch, "shutdown"):
            orch.shutdown()
        try:
            self._webcam.stop()
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        tray_ok = self._tray is not None and self._settings.minimize_to_tray
        if not self._force_quitting and tray_ok:
            event.ignore()
            self._hide_to_tray()
            return
        self._shutdown_sequence()
        event.accept()
        QApplication.instance().quit()
