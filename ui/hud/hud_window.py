"""Sinematik JARVIS HUD penceresi.

Davranis (motor/orkestrator sinyalleri, onay diyaloglari, tepsi, capture-exclusion, dis
yazmada kenara cekilme...) `MainWindow`'dan aynen miras alinir; burada yalnizca yerlesim
degisir. `MainWindow` handler'larinin kullandigi oznitelikler (`_graph`, `_log`, `_mic_btn`,
`_left_sidebar`, `_sb_*`...) ayni adlarla uretilir.

    ┌ J A R V I S · ● BAĞLI ─────────────── [ODAK][MİK][KAM][EKRAN]… ┐
    │ ZAMAN        │                                 │ SİSTEM        │
    │ OKUL         │  zirh bustu + gogus reactor'u   │ AJANLAR       │
    │ GÖREVLER     │      DİNLİYOR / altyazı         │ GÜNLÜK        │
    │ GÖRÜŞ        │      (KONUŞMA çekmecesi)        │               │
    │ >_ komut satırı ....................................... [KONUŞMA]│
    └ durum çubuğu ────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.hud.backdrop import HudBackdrop
from ui.hud.boot import BootOverlay
from ui.hud.hud_card import HudCard
from ui.hud.stat_cards import ClockCard, OkulCard, SystemCard
from ui.main_window import MainWindow, _elide
from ui.widgets.agent_panel import AgentPanel
from ui.hud.suit_core import SuitCore
from ui.widgets.log_view import LogView
from ui.widgets.transcript_view import TranscriptView
from ui.widgets.webcam_view import WebcamView

LEFT_W = 272
RIGHT_W = 300
TAG_MIN_W = 1280
GREETING = "“Emrinizdeyim efendim.”"


class _PreviewView(WebcamView):
    """Tiklanabilir kucuk canli onizleme (kamera / ekran)."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        self.clicked.emit()
        super().mousePressEvent(event)


class HudWindow(MainWindow):
    def _build_ui(self) -> None:
        self._booted = False
        self._vision_expanded = False

        root = HudBackdrop()
        self._backdrop = root
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(14, 12, 14, 8)
        body.setSpacing(14)
        body.addWidget(self._build_left_column())
        body.addWidget(self._build_core(), 1)
        body.addWidget(self._build_right_column())
        outer.addLayout(body, 1)
        outer.addWidget(self._build_command_bar())
        outer.addWidget(self._build_statusbar())
        self._splitter = None

        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._leave_fullscreen)

    # ================================================================ ust serit
    def _chip(self, text: str, tip: str, *, checkable: bool = False, danger: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("hudChipDanger" if danger else "hudChip")
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("hudTopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 12, 8)
        lay.setSpacing(4)

        brand = QLabel("JARVIS")
        brand.setObjectName("hudWordmark")
        lay.addWidget(brand)
        tag = QLabel("KİŞİSEL ASİSTAN  ·  GEMINI LIVE")
        tag.setObjectName("hudTag")
        self._tag = tag   # dar pencerede gizlenir (bkz. resizeEvent); minimum genislige katilmaz
        tag.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(tag)
        lay.addSpacing(14)
        self._conn_pill = QLabel()
        self._conn_pill.setObjectName("statusItem")
        self._set_conn(self._conn_pill, "BAĞLANIYOR", theme.WARN)
        lay.addWidget(self._conn_pill)
        lay.addStretch(1)

        self._home_btn = self._chip("ODAK", "Odak modu: yan kartları gizle / göster", checkable=True)
        self._home_btn.toggled.connect(self._toggle_focus_mode)
        self._mic_btn = self._chip("MİK", "Mikrofon (aç/kapa)", checkable=True)
        self._mic_btn.setChecked(True)
        self._mic_btn.toggled.connect(self._on_mic_toggled)
        # Uyandirma kelimesi MIK'in acilir menusunde: ayri chip 1024 px genislige sigmiyor
        self._wake_btn = QAction("Uyandırma kelimesi — yalnızca 'Hey JARVIS' deyince dinle", self)
        self._wake_btn.setCheckable(True)
        self._wake_btn.setChecked(self._settings.wake_word_enabled)
        self._wake_btn.toggled.connect(self._on_wake_toggled)
        mic_menu = QMenu(self._mic_btn)
        mic_menu.addAction(self._wake_btn)
        self._mic_btn.setMenu(mic_menu)
        self._mic_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._cam_btn = self._chip("KAM", "Kamera (aç/kapa)", checkable=True)
        self._cam_btn.setChecked(self._settings.webcam_enabled)
        self._cam_btn.toggled.connect(self._on_cam_toggled)
        self._screen_btn = self._chip("EKRAN", "Ekran görüşü (aç/kapa)", checkable=True)
        self._screen_btn.setChecked(self._settings.screen_enabled)
        self._screen_btn.toggled.connect(self._on_screen_toggled)
        self._hud_btn = self._chip("JEST", "Jest HUD (3D kontrol)")
        self._hud_btn.clicked.connect(self._open_gesture_hud)
        self._team_btn = self._chip("EKİP", "Stark Ekibi (aç/kapa)", checkable=True)
        self._team_btn.toggled.connect(self._toggle_stark_team)
        self._left_btn = self._chip("SOL", "Sol kartları göster/gizle", checkable=True)
        self._left_btn.setChecked(True)
        self._left_btn.toggled.connect(lambda v: self._toggle_panel("left", v))
        self._right_btn = self._chip("SAĞ", "Sağ kartları göster/gizle", checkable=True)
        self._right_btn.setChecked(True)
        self._right_btn.toggled.connect(lambda v: self._toggle_panel("right", v))
        self._full_btn = self._chip("TAM EKRAN", "Sinematik tam ekran (F11)", checkable=True)
        self._full_btn.toggled.connect(self._set_fullscreen)
        self._top_btn = self._chip("ÜSTTE", "Her zaman üstte", checkable=True)
        self._top_btn.setChecked(self._settings.always_on_top)
        self._top_btn.toggled.connect(self._apply_on_top)
        self._tray_btn = self._chip("TEPSİ", "Tepsiye küçült")
        self._tray_btn.clicked.connect(self._hide_to_tray)
        self._stop_btn = self._chip("⏻", "Çıkış", danger=True)
        self._stop_btn.clicked.connect(self._force_quit)

        groups = (
            (self._home_btn,),
            (self._mic_btn, self._cam_btn, self._screen_btn, self._hud_btn, self._team_btn),
            (self._left_btn, self._right_btn, self._full_btn, self._top_btn),
            (self._tray_btn, self._stop_btn),
        )
        for i, group in enumerate(groups):
            if i:
                lay.addSpacing(2)
            for btn in group:
                lay.addWidget(btn)
        return bar

    # ================================================================ sol sutun
    def _build_left_column(self) -> QWidget:
        col = QWidget()
        col.setFixedWidth(LEFT_W)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._clock_card = ClockCard(self._settings.hud_weather_location)
        lay.addWidget(self._clock_card)
        self._okul_card = OkulCard()
        lay.addWidget(self._okul_card)

        # AgentPanel mantigi tek nesnede kalir; parcalari farkli kartlara dagitilir
        self._agent_panel = AgentPanel(col)
        self._agent_panel.agent_selected.connect(self._on_agent_selected)
        parts = self._agent_panel.sections()

        self._tasks_card = HudCard("GÖREV AKIŞI", "04")
        self._tasks_card.body.addWidget(parts["feed"], 1)
        lay.addWidget(self._tasks_card, 1)

        self._vision_card = HudCard("CANLI GÖRÜŞ", "05")
        self._vision_card.set_meta("tıkla: büyüt")
        self._vision_box = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._vision_box.setSpacing(6)
        self._webcam_view = _PreviewView(self._webcam.get_latest_jpeg, placeholder="KAMERA KAPALI")
        self._screen_view = _PreviewView(self._screen_frame, placeholder="EKRAN KAPALI")
        for view, active in ((self._webcam_view, self._settings.webcam_enabled),
                             (self._screen_view, self._settings.screen_enabled)):
            view.setMinimumSize(100, 72)
            view.set_active(active)
            view.clicked.connect(self._toggle_vision_size)
            view.setCursor(Qt.CursorShape.PointingHandCursor)
            self._vision_box.addWidget(view)
        self._vision_card.body.addLayout(self._vision_box)
        lay.addWidget(self._vision_card)

        self._left_sidebar = col
        self._parts = parts
        return col

    def _toggle_vision_size(self) -> None:
        self._vision_expanded = not self._vision_expanded
        big = self._vision_expanded
        self._vision_box.setDirection(
            QBoxLayout.Direction.TopToBottom if big else QBoxLayout.Direction.LeftToRight
        )
        for view in (self._webcam_view, self._screen_view):
            view.setMinimumSize(100, 150 if big else 72)
        self._vision_card.set_meta("tıkla: küçült" if big else "tıkla: büyüt")

    # ================================================================ merkez
    def _build_core(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        self._graph = SuitCore()   # BrainGraph ile ayni API; departmanlar sag ustteki kadranda
        self._graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._graph.node_clicked.connect(self._on_agent_selected)   # ajan adi ya da "dept:<key>"
        v.addWidget(self._graph, 1)

        self._state_line = QLabel("HAZIR")
        self._state_line.setObjectName("hudState")
        self._state_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_line.setStyleSheet(f"color:{theme.STATE_IDLE};")
        v.addWidget(self._state_line)

        self._caption = QLabel("")
        self._caption.setObjectName("hudCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        self._caption.setMinimumHeight(46)
        v.addWidget(self._caption)

        self._talk_card = HudCard("KONUŞMA", "06")
        self._transcript = TranscriptView()
        self._talk_card.body.addWidget(self._transcript, 1)
        self._talk_card.setMaximumHeight(280)
        self._talk_card.setMinimumHeight(180)
        self._talk_card.hide()
        v.addWidget(self._talk_card)
        return wrap

    # ================================================================ sag sutun
    def _build_right_column(self) -> QWidget:
        col = QWidget()
        col.setFixedWidth(RIGHT_W)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        model_name = str(getattr(self._settings, "model", "") or "").removeprefix("models/").removesuffix("-latest")
        self._system_card = SystemCard(_elide(model_name, 30))
        lay.addWidget(self._system_card)

        self._agents_card = HudCard("AJANLAR", "07", collapsible=True)
        tree = self._parts["tree"]
        tree.setMinimumHeight(120)
        self._agents_card.body.addWidget(tree, 3)
        detail = self._parts["detail"]
        detail.setMaximumHeight(130)
        self._agents_card.body.addWidget(detail, 2)
        lay.addWidget(self._agents_card, 3)

        self._log_card = HudCard("SİSTEM GÜNLÜĞÜ", "08", collapsible=True)
        self._log = LogView()
        self._log_card.body.addWidget(self._log, 1)
        lay.addWidget(self._log_card, 2)

        self._right_sidebar = col
        return col

    # ============================================================ komut satiri
    def _build_command_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 2, 14, 10)
        lay.setSpacing(8)
        prompt = QLabel(">_")
        prompt.setObjectName("hudPrompt")
        lay.addWidget(prompt)
        self._bridge_input = QLineEdit()
        self._bridge_input.setObjectName("commandInput")
        self._bridge_input.setPlaceholderText("JARVIS'e yaz — Enter ile canlı oturuma gönder")
        self._bridge_input.returnPressed.connect(self._on_bridge_send)
        lay.addWidget(self._bridge_input, 1)
        send = QPushButton("GÖNDER")
        send.clicked.connect(self._on_bridge_send)
        lay.addWidget(send)
        self._talk_btn = self._chip("KONUŞMA", "Konuşma geçmişini aç/kapa", checkable=True)
        self._talk_btn.toggled.connect(self._talk_card.setVisible)
        lay.addWidget(self._talk_btn)
        return bar

    # ============================================================ davranis eki
    def _on_agents_loaded(self, agents: list) -> None:
        super()._on_agents_loaded(agents)
        depts = {getattr(getattr(a, "department", None), "value", "") for a in agents} - {""}
        self._agents_card.set_meta(f"{len(depts)} departman · {len(agents)} ajan")

    def _on_orch_task(self, update: object) -> None:
        super()._on_orch_task(update)
        self._tasks_card.set_meta(self._sb_tasks.text().replace("GÖREV ", "") + " aktif/toplam")

    def _toggle_fullscreen(self) -> None:
        self._full_btn.setChecked(not self.isFullScreen())

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self._full_btn.setChecked(False)

    def _set_fullscreen(self, on: bool) -> None:
        if on and not self.isFullScreen():
            self.showFullScreen()
        elif not on and self.isFullScreen():
            self.showNormal()
        self._exclude_from_capture()

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        if not self._booted:
            self._booted = True
            boot = BootOverlay(self.centralWidget())
            boot.finished.connect(self._after_boot)
            self._boot = boot
            boot.start()

    def _after_boot(self) -> None:
        self._boot = None
        if not self._caption.text():
            self._caption.setText(GREETING)

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        # 1366 px dizustu ekranlarda ust serit sigsin: slogan etiketi yer kaplamasin
        self._tag.setVisible(self.width() >= TAG_MIN_W)

    def changeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().changeEvent(event)
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.WindowStateChange:
            self._backdrop.set_active(not self.isMinimized())
            if hasattr(self, "_full_btn") and self._full_btn.isChecked() != self.isFullScreen():
                self._set_checked_silently(self._full_btn, self.isFullScreen())
