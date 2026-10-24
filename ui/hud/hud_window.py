"""CYRAEN "Komuta" HUD penceresi.

Davranis (motor/orkestrator sinyalleri, onay diyaloglari, tepsi, capture-exclusion, dis
yazmada kenara cekilme...) `MainWindow`'dan aynen miras alinir; burada yalnizca yerlesim
degisir. `MainWindow` handler'larinin kullandigi oznitelikler (`_graph`, `_log`, `_mic_btn`,
`_left_sidebar`, `_sb_*`...) ayni adlarla uretilir.

    ┌ ◎ CYRAEN Komuta · ● BAĞLI ─────────────── [ODAK][MİK][KAM][EKRAN]… ┐
    │ ŞİMDİ      │  ┌ CYRAEN Komuta ────────────┐  │ CANLI GÖRÜŞ        │
    │ OKUL       │  │  ajan rozet halkasi        │  │ GÖREVLER           │
    │ SİSTEM     │  │  departman halkasi         │  │ HIZLI KOMUTLAR     │
    │ AJANLAR    │  │  parcacik cekirdegi        │  │ RUTİNLER           │
    │            │  └ son gunluk satiri ─────────┘  │ SİSTEM GÜNLÜĞÜ     │
    │ >_ komut satırı ......................................... [KONUŞMA]│
    └ durum çubuğu ──────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import personas
from ui import theme
from ui.hud.backdrop import HudBackdrop
from ui.hud import boot3d, orb_view
from ui.hud.boot import BootOverlay
from ui.hud.command_graph import CommandGraph
from ui.hud.hud_card import HudCard
from ui.hud.persona_card import PersonaCard
from ui.hud.persona_fx import PersonaOverlay
from ui.hud.stat_cards import ClockCard, OkulCard, QuickCommandsCard, RoutinesCard, SystemCard
from ui.main_window import MainWindow, _elide, _state_text
from ui.widgets.agent_panel import AgentPanel
from ui.widgets.log_view import LogView
from ui.widgets.transcript_view import TranscriptView
from ui.widgets.webcam_view import WebcamView

LEFT_W = 272
RIGHT_W = 300
TAG_MIN_W = 1280
GREETING = theme.BRANDING["cyraen"]["greeting"]   # kisilige gore: theme.branding()["greeting"]
THINK_TIMEOUT_MS = 20000   # arac sonucu hic gelmezse orb "dusunme"den ciksin


class _PreviewView(WebcamView):
    """Tiklanabilir kucuk canli onizleme (kamera / ekran)."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        self.clicked.emit()
        super().mousePressEvent(event)


class _TickerLog(LogView):
    """Gunluk + her yeni satiri (orta tuvalin altindaki serit icin) sinyalle bildirir."""

    line_added = Signal(str)

    def _line(self, color: str, text: str) -> None:
        super()._line(color, text)
        self.line_added.emit(text.splitlines()[0] if text else "")


class _MirrorLabel(QLabel):
    """Metni ayrica orb sayfasina da aktaran etiket (orb varken etiketin kendisi gizlidir).

    `MainWindow` isleyicileri `_state_line` / `_caption` uzerinden yazar; boylece onlara
    dokunmadan metin orb'un altindaki Zoey tarzi arayuze gider.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.mirror: Callable[[str], None] | None = None

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        if self.mirror is not None:
            self.mirror(text)


def _glow(widget: QWidget, color: str, blur: float, alpha: int) -> None:
    """Zoey'deki `text-shadow` isimasi (Qt etiketlerinde golge efektiyle)."""
    effect = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(alpha)
    effect.setColor(c)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)


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
        body.setContentsMargins(12, 12, 12, 8)
        body.setSpacing(12)
        body.addWidget(self._build_left_column())
        body.addWidget(self._build_core(), 1)
        body.addWidget(self._build_right_column())
        outer.addLayout(body, 1)
        outer.addWidget(self._build_command_bar())
        outer.addWidget(self._build_statusbar())
        self._splitter = None

        # ULTRON'un tarama cizgisi/glitch katmani: her seyin ustunde, fareye seffaf
        self._fx_overlay = PersonaOverlay(root)
        self._fx_overlay.glitched.connect(self._on_glitch)
        self.apply_persona_theme(personas.load_active(self._settings).key)

        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)
        QShortcut(QKeySequence(Qt.Key.Key_F9), self, activated=self._show_armor)

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

    def _wordmark(self) -> QHBoxLayout:
        """Zoey'nin "ZOEY_OS" logosu gibi: kisilik renginde isiyan mono "<AD>_OS"."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        brand = QLabel(f"{theme.branding()['wordmark']}_OS")
        brand.setObjectName("hudWordmark")
        _glow(brand, theme.ACCENT_BASE, 22, 150)
        self._brand = brand
        row.addWidget(brand)
        return row

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("hudTopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 12, 8)
        lay.setSpacing(4)
        brand = QVBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        brand.setSpacing(0)
        brand.addLayout(self._wordmark())
        tag = QLabel(theme.branding()["tag"])
        tag.setObjectName("hudTag")
        self._tag = tag   # dar pencerede gizlenir (bkz. resizeEvent); minimum genislige katilmaz
        tag.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        brand.addWidget(tag)
        lay.addLayout(brand)
        lay.addSpacing(8)
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
        self._wake_btn = QAction(f"Uyandırma kelimesi — yalnızca '{self._settings.wake_phrase}' deyince dinle", self)
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
        # 3B zirh JEST'in acilir menusunde (ayri chip 1024 px genislige sigmiyor)
        armor_act = QAction("3B zırhı göster  (F9)", self)
        armor_act.triggered.connect(self._show_armor)
        hud_menu = QMenu(self._hud_btn)
        hud_menu.addAction(armor_act)
        self._hud_btn.setMenu(hud_menu)
        self._hud_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._team_btn = self._chip("EKİP", "Stark Ekibi (aç/kapa)", checkable=True)
        self._team_btn.toggled.connect(self._toggle_stark_team)
        self._left_btn = self._chip("SOL", "Sol kartları göster/gizle", checkable=True)
        self._left_btn.setChecked(True)
        self._left_btn.toggled.connect(lambda v: self._toggle_panel("left", v))
        self._right_btn = self._chip("SAĞ", "Sağ kartları göster/gizle", checkable=True)
        self._right_btn.setChecked(True)
        self._right_btn.toggled.connect(lambda v: self._toggle_panel("right", v))
        self._full_btn = self._chip("TAM EKRAN", "Tam ekran (F11)", checkable=True)
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

    # ============================================================ kart sutunu
    @staticmethod
    def _column(width: int) -> tuple[QScrollArea, QVBoxLayout]:
        """Sabit genislikte, kendi icinde kayan kart sutunu (kucuk ekranda kartlar ezilmez)."""
        area = QScrollArea()
        area.setObjectName("hudColumn")
        area.setFixedWidth(width)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("hudColumnBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        area.setWidget(body)
        return area, lay

    # ================================================================ sol sutun
    def _build_left_column(self) -> QWidget:
        col, lay = self._column(LEFT_W)

        self._clock_card = ClockCard(self._settings.hud_weather_location)
        lay.addWidget(self._clock_card)
        self._okul_card = OkulCard()
        lay.addWidget(self._okul_card)
        model_name = str(getattr(self._settings, "model", "") or "").removeprefix("models/").removesuffix("-latest")
        self._system_card = SystemCard(_elide(model_name, 30))
        lay.addWidget(self._system_card)

        # AgentPanel mantigi tek nesnede kalir; parcalari farkli kartlara dagitilir
        self._agent_panel = AgentPanel(col)
        self._agent_panel.agent_selected.connect(self._on_agent_selected)
        parts = self._agent_panel.sections()

        self._agents_card = HudCard("AJANLAR", collapsible=True)
        tree = parts["tree"]
        tree.setMinimumHeight(120)
        self._agents_card.body.addWidget(tree, 1)
        detail = parts["detail"]
        detail.setMaximumHeight(130)
        detail.hide()   # bir ajan secilince acilir (bkz. _on_agent_selected)
        self._agents_card.body.addWidget(detail)
        lay.addWidget(self._agents_card, 1)

        self._left_sidebar = col
        self._parts = parts
        return col

    # ================================================================ merkez
    def _build_core(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Zoey'deki gibi cercevesiz: orb dogrudan siyah zeminde durur
        canvas = QFrame()
        canvas.setObjectName("hudCanvas")
        cv = QVBoxLayout(canvas)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(2)

        self._state_line = _MirrorLabel("HAZIR")
        self._state_line.setObjectName("hudState")
        self._state_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_line.setStyleSheet(f"color:{theme.STATE_IDLE};")
        cv.addWidget(self._state_line)

        # Merkez: Zoey OS orb'u (QtWebEngine); yoksa ya da acilamazsa komuta grafi
        self._orb: orb_view.OrbView | None = None
        self._last_agents: list = []
        self._waiting_for_orb = False
        self._pending_tools = 0
        self._think_timer = QTimer(self)
        self._think_timer.setSingleShot(True)
        self._think_timer.timeout.connect(lambda: self._set_thinking(0))
        if orb_view.available():
            self._orb = orb_view.OrbView()
            self._orb.mic_clicked.connect(self._mic_btn.click)
            self._orb.failed.connect(self._orb_failed)
            self._graph = self._orb
        else:
            self._graph = self._make_command_graph()
        self._graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cv.addWidget(self._mount_panel(self._graph), 1)   # icerik paneli merkez gorselin yerinde acilir

        self._caption = _MirrorLabel("")
        self._caption.setObjectName("hudCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        self._caption.setMinimumHeight(44)
        self._caption.setContentsMargins(14, 0, 14, 0)
        cv.addWidget(self._caption)

        if self._orb is not None:
            # durum + alt yazi orb'un altindaki Zoey arayuzunde gosterilir
            self._state_line.mirror = self._orb.set_status
            self._caption.mirror = self._orb.set_caption
            self._orb.set_status(self._state_line.text())
            self._state_line.hide()
            self._caption.hide()

        self._ticker = QLabel("")
        self._ticker.setObjectName("hudTicker")
        self._ticker.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)   # uzun satir kirpilir
        cv.addWidget(self._ticker)
        v.addWidget(canvas, 1)

        self._talk_card = HudCard("KONUŞMA")
        self._transcript = TranscriptView()
        self._talk_card.body.addWidget(self._transcript, 1)
        self._talk_card.setMaximumHeight(280)
        self._talk_card.setMinimumHeight(180)
        self._talk_card.hide()
        v.addWidget(self._talk_card)
        return wrap

    def _make_command_graph(self) -> CommandGraph:
        graph = CommandGraph()   # BrainGraph ile ayni API
        graph.node_clicked.connect(self._on_agent_selected)   # ajan adi ya da "dept:<key>"
        return graph

    def _orb_failed(self) -> None:
        """Orb sayfasi acilamadi: ayni yere klasik komuta grafi konur, etiketler geri gelir."""
        orb, self._orb = self._orb, None
        if orb is None:
            return
        graph = self._make_command_graph()
        graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        showing_orb = self._center_stack.currentWidget() is orb
        self._center_stack.insertWidget(0, graph)
        self._center_stack.removeWidget(orb)
        orb.deleteLater()
        self._graph = graph
        if self._last_agents:
            graph.set_agents(self._last_agents)
        if showing_orb:
            self._center_stack.setCurrentWidget(graph)
        self._state_line.mirror = None
        self._caption.mirror = None
        self._state_line.show()
        self._caption.show()
        if getattr(self, "_waiting_for_orb", False):   # acilis orb'a birakilmisti
            self._waiting_for_orb = False
            self._after_boot()

    def _set_thinking(self, delta: int) -> None:
        """Arac cagrisi suruyorken orb Zoey'deki gibi hizlanir ve parlar."""
        self._pending_tools = 0 if delta == 0 else max(0, self._pending_tools + delta)
        if self._orb is not None:
            self._orb.set_thinking(self._pending_tools > 0)
        if self._pending_tools > 0:
            self._think_timer.start(THINK_TIMEOUT_MS)
        else:
            self._think_timer.stop()

    def _on_tool_call(self, names: list) -> None:
        super()._on_tool_call(names)
        self._set_thinking(+max(1, len(names)))

    def _on_tool_result(self, name: str, ok: bool, detail: str) -> None:
        super()._on_tool_result(name, ok, detail)
        self._set_thinking(-1)

    def _on_state(self, state: str) -> None:
        super()._on_state(state)
        if self._orb is not None:
            self._orb.set_asleep(state == "idle" and self._wake_asleep)

    def _set_ticker(self, text: str) -> None:
        width = max(60, self._ticker.width() - 26)
        self._ticker.setText(self._ticker.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width))

    # ================================================================ sag sutun
    def _build_right_column(self) -> QWidget:
        col, lay = self._column(RIGHT_W)

        self._vision_card = HudCard("CANLI GÖRÜŞ")
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

        self._tasks_card = HudCard("GÖREVLER")
        count_row = QHBoxLayout()
        count_row.setSpacing(10)
        self._task_count_label = QLabel("0")
        self._task_count_label.setObjectName("hudCount")
        count_row.addWidget(self._task_count_label)
        self._task_sub_label = QLabel("aktif görev\n0 toplam")
        self._task_sub_label.setObjectName("hudKey")
        count_row.addWidget(self._task_sub_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self._tasks_card.body.addLayout(count_row)
        feed = self._parts["feed"]
        feed.setMinimumHeight(80)
        self._tasks_card.body.addWidget(feed, 1)
        lay.addWidget(self._tasks_card, 3)

        self._quick_card = QuickCommandsCard()
        self._quick_card.command.connect(self._on_quick_command)
        lay.addWidget(self._quick_card)

        self._routines_card = RoutinesCard()
        lay.addWidget(self._routines_card)

        self._log_card = HudCard("SİSTEM GÜNLÜĞÜ", collapsible=True)
        self._log = _TickerLog()
        self._log.setMinimumHeight(96)
        self._log.line_added.connect(self._set_ticker)
        self._log_card.body.addWidget(self._log, 1)
        lay.addWidget(self._log_card, 2)

        self._persona_card = PersonaCard(personas.load_active(self._settings).key)
        self._persona_card.selected.connect(self._on_persona_selected)
        lay.addWidget(self._persona_card)

        self._right_sidebar = col
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

    # ============================================================ komut satiri
    def _build_command_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 2, 12, 10)
        lay.setSpacing(8)
        prompt = QLabel(">_")
        prompt.setObjectName("hudPrompt")
        lay.addWidget(prompt)
        self._bridge_input = QLineEdit()
        self._bridge_input.setObjectName("commandInput")
        self._bridge_input.setPlaceholderText(theme.branding()["placeholder"])
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
    def _on_quick_command(self, text: str) -> None:
        """Hizli komut dosemesi: komut satirindan yazilmis gibi canli oturuma gonderilir."""
        if self._worker is None:
            return
        self._worker.inject_bridge_message(text)
        self._transcript.add_system(f"Sen (hızlı komut): {text}")

    def _on_persona_selected(self, key: str) -> None:
        """EKİPLER cipi: motor kisiligi degistirip yeniden baglanir, on_persona ile doner."""
        if self._worker is None or key == self._persona_card.active:
            return
        self._worker.set_persona(key)

    def _on_persona(self, key: str) -> None:
        super()._on_persona(key)   # tema da burada uygulanir (apply_persona_theme)
        self._persona_card.set_active(key)

    # ========================================================= kisilik temasi
    def apply_persona_theme(self, key: str) -> str:
        """Tum HUD'u kisilige gecirir: palet + QSS, donmus renkler, metinler, orb, efekt."""
        greeting_before = self._caption.text() == theme.branding()["greeting"]
        key = super().apply_persona_theme(key)
        brand = theme.branding(key)
        self._brand.setText(f"{brand['wordmark']}_OS")
        _glow(self._brand, theme.ACCENT_BASE, 22, 150)
        self._tag.setText(brand["tag"])
        self._bridge_input.setPlaceholderText(brand["placeholder"])
        if greeting_before:
            self._caption.setText(brand["greeting"])
        if not getattr(self, "_wake_asleep", False):   # durum yazisi yeni renkte
            self._state_line.setStyleSheet(f"color:{_state_text(getattr(self, '_last_state', 'idle'))[1]};")
        if self._orb is not None:
            self._orb.set_theme({
                "persona": key, "accent": theme.ACCENT, "base": theme.ACCENT_BASE,
                "equator": theme.ORB_COLORS[0], "pole": theme.ORB_COLORS[1],
            })
        return key

    def _on_glitch(self, active: bool) -> None:
        """ULTRON glitch'i: logo birkac piksel kayar, kizil/camgobegi renk ayrismasi."""
        if active:
            self._brand.setContentsMargins(self._fx_overlay.width() % 5 + 2, 0, 0, 0)
            _glow(self._brand, "#00e6ff", 6, 230)
        else:
            self._brand.setContentsMargins(0, 0, 0, 0)
            _glow(self._brand, theme.ACCENT_BASE, 22, 150)

    def _on_agents_loaded(self, agents: list) -> None:
        self._last_agents = agents   # orb acilamazsa yerine gelen grafa aktarilir
        super()._on_agents_loaded(agents)
        depts = {getattr(getattr(a, "department", None), "value", "") for a in agents} - {""}
        self._agents_card.set_meta(f"{len(depts)} departman · {len(agents)} ajan")

    def _on_agent_selected(self, name: str) -> None:
        super()._on_agent_selected(name)
        if not name.startswith("dept:"):
            self._parts["detail"].show()

    def _on_orch_task(self, update: object) -> None:
        super()._on_orch_task(update)
        counts = self._sb_tasks.text().replace("GÖREV ", "")
        active, _, total = counts.partition("/")
        self._tasks_card.set_meta(counts + " aktif/toplam")
        self._task_count_label.setText(active)
        self._task_sub_label.setText(f"aktif görev\n{total} toplam")

    def _toggle_fullscreen(self) -> None:
        self._full_btn.setChecked(not self.isFullScreen())

    def _on_escape(self) -> None:
        """Esc: once 3B zirh ekranini, sonra acik icerik panelini kapatir; yoksa tam ekrandan cikar."""
        boot = getattr(self, "_boot", None)
        if isinstance(boot, boot3d.Boot3DOverlay):
            boot.dismiss()
            return
        if not self._close_panel():
            self._leave_fullscreen()

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
            self._play_boot()

    def _play_boot(self, mode: str = "boot") -> None:
        """Acilis: Zoey orb'u uzaktan suzulerek gelir; ya da 3B zirh / klasik halka animasyonu."""
        style = self._settings.boot_style
        if mode == "boot" and style == "orb" and self._orb is not None:
            # ayri katman yok: orb sayfasi yuklenince kendisi gelir, oturunca selamlanir
            self._waiting_for_orb = True
            self._orb.landed.connect(self._on_orb_landed)
            return
        use_3d = style == "3d" and boot3d.available()
        if mode == "idle" and boot3d.available():
            use_3d = True   # F9: zirh her zaman istenebilir
        if use_3d:
            hold = self._settings.boot_hold_s if mode == "boot" else 0.0
            boot = boot3d.Boot3DOverlay(self.centralWidget(), mode=mode, hold_s=hold)
        elif mode == "boot":
            boot = BootOverlay(self.centralWidget())
        else:
            self._set_ticker("3B zırh kullanılamıyor (web3d derlenmemiş ya da QtWebEngine yok)")
            return
        boot.finished.connect(self._after_boot)
        self._boot = boot
        boot.start()

    def _on_orb_landed(self) -> None:
        if self._waiting_for_orb:
            self._waiting_for_orb = False
            self._after_boot()

    def _show_armor(self) -> None:
        """3B zirhi acilis animasyonu olmadan, etkilesimli halde yeniden gosterir."""
        if getattr(self, "_boot", None) is None and self._booted:
            self._play_boot(mode="idle")

    def _after_boot(self) -> None:
        self._boot = None
        if not self._caption.text():
            self._caption.setText(theme.branding()["greeting"])

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
