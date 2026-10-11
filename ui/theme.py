"""Arayuz paleti + global stil (QSS).

Iron Man / holografik HUD estetigi: derin uzay-siyahi zemin, holografik camgobegi
(cyan) birincil, Iron Man altini ikincil, mistik menekse ucuncul vurgu. Ince parlak
cizgiler, monospace HUD etiketleri. Eski isimler geriye uyumluluk icin korunur.
"""

from __future__ import annotations

# --- HUD paleti ------------------------------------------------------------
BG_SPACE = "#05070d"       # en arka zemin
BG_MAIN = "#070a12"        # ana calisma alani
BG_RIBBON = "#04060b"      # sol dikey serit
BG_SIDEBAR = "#080b14"     # kenar panelleri
BG_CARD = "#0d1220"        # yuzeyler
BG_CARD_HOVER = "#121a2c"
BG_INPUT = "#080c16"
BG_STATUSBAR = "#04060b"
BG_GLASS = "#0b1120"       # yari-saydam panel hissi

BORDER = "#16233a"
BORDER_LIGHT = "#22344f"
GRID = "#0f2033"           # hex/izgara cizgileri

ACCENT = "#34e3f0"         # holografik camgobegi (birincil)
ACCENT_BASE = "#22c9e0"
ACCENT_DIM = "#1c5a68"
STATE_IDLE = "#3f8fa0"       # "HAZIR" durum yazisi: ACCENT_DIM metin icin fazla koyu (~2.6:1)
ACCENT_HOVER = "#6af2ff"
GOLD = "#ffb84d"           # Iron Man altini (ikincil)
GOLD_DIM = "#6b4e26"
MYSTIC = "#b47cff"         # mistik menekse (ucuncul)
MYSTIC_DIM = "#4c3a73"

SPEAK = GOLD               # model konusurken altin
GOOD = "#3ff5b0"
WARN = "#ffcf4d"
BAD = "#ff5c72"

TEXT = "#cfe6ef"
TEXT_DIM = "#7f97a6"
TEXT_MUTED = "#7f97a6"
TEXT_FAINT = "#6a8394"       # ~4.9:1 kenar paneli zemininde (WCAG AA)

USER_COLOR = "#6fd8ff"
JARVIS_COLOR = "#ffcf8a"

# --- sinematik HUD (ui/hud) ------------------------------------------------
HUD_GLASS = (9, 15, 28, 178)        # kart zemini (RGBA; QPainter'da kullanilir)
HUD_GLASS_QSS = "rgba(9, 15, 28, 178)"
HUD_EDGE = "#1f4a5c"                # kart kenari
HUD_TICK = ACCENT                   # kart kose isareti

# --- geriye uyumlu takma adlar -------------------------------------------
BG_DEEP = BG_MAIN
BG_PANEL = BG_SIDEBAR
BG_PANEL_ALT = BG_CARD

FONT_FAMILY = '"Rajdhani", "Titillium Web", "Segoe UI", system-ui, sans-serif'
MONO_FAMILY = '"JetBrains Mono", "Share Tech Mono", "Cascadia Mono", "Consolas", monospace'


QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow, QWidget#root {{ background-color: {BG_MAIN}; }}

/* --- sol ikon serit --- */
QFrame#ribbon {{ background-color: {BG_RIBBON}; border-right: 1px solid {BORDER}; }}
QToolButton#ribbonBtn {{
    background: transparent; border: 1px solid transparent; border-radius: 9px;
    padding: 7px; font-size: 17px; color: {TEXT_DIM};
}}
QToolButton#ribbonBtn:hover {{
    background-color: {BG_CARD}; color: {ACCENT_HOVER};
    border: 1px solid {ACCENT_DIM};
}}
QToolButton#ribbonBtn:checked {{
    background-color: {BG_CARD}; color: {ACCENT};
    border: 1px solid {ACCENT_BASE};
}}
QToolButton#ribbonBtn:pressed {{ background-color: {BORDER}; }}

/* --- kenar panelleri --- */
QFrame#sidebar {{ background-color: {BG_SIDEBAR}; }}

QLabel#navHeader {{
    color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 10px;
    font-weight: 700; letter-spacing: 3px; padding: 12px 12px 5px 12px;
}}

/* --- sekme cubugu --- */
QFrame#tabbar {{ background-color: {BG_SIDEBAR}; border-bottom: 1px solid {BORDER}; }}
QLabel#tab {{
    background-color: {BG_MAIN}; color: {ACCENT};
    font-family: {MONO_FAMILY}; letter-spacing: 2px; font-size: 12px;
    padding: 8px 18px; border-right: 1px solid {BORDER};
    border-top: 2px solid {ACCENT};
}}

/* --- durum cubugu --- */
QFrame#statusbar {{ background-color: {BG_STATUSBAR}; border-top: 1px solid {BORDER}; }}
QLabel#statusItem {{
    color: {TEXT_DIM}; font-family: {MONO_FAMILY}; font-size: 11px; padding: 0 9px;
    letter-spacing: 1px;
}}
QLabel#statusSep {{ color: {BORDER_LIGHT}; }}

/* --- basliklar --- */
QLabel#title {{
    font-size: 16px; font-weight: 700; letter-spacing: 8px; color: {ACCENT};
    font-family: {MONO_FAMILY};
}}
QLabel#subtitle {{
    color: {GOLD_DIM}; font-size: 10px; letter-spacing: 3px; font-family: {MONO_FAMILY};
}}
QLabel#sectionLabel {{
    color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 10px;
    font-weight: 700; letter-spacing: 3px;
}}
QLabel#caption {{ color: {TEXT_DIM}; font-size: 13px; font-style: italic; }}
QLabel#stateLine {{
    font-size: 13px; font-weight: 700; letter-spacing: 6px; font-family: {MONO_FAMILY};
}}

/* --- metin alanlari --- */
QTextEdit, QPlainTextEdit {{
    background-color: transparent; border: none; padding: 6px;
    selection-background-color: {ACCENT_DIM};
}}
QPlainTextEdit#log {{
    background-color: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: {MONO_FAMILY}; font-size: 11px; color: {TEXT_DIM};
}}
QListWidget, QTreeWidget {{
    background-color: transparent; border: none; outline: none; color: {TEXT_DIM};
}}
QListWidget::item, QTreeWidget::item {{ padding: 5px 8px; border-radius: 6px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background-color: {BG_CARD}; color: {TEXT}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {BG_CARD}; color: {ACCENT};
}}
QTreeWidget::branch {{ background: transparent; }}
QTextEdit#log {{
    background-color: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    font-size: 11px;
}}

QLineEdit {{
    background-color: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px; color: {TEXT}; font-family: {MONO_FAMILY}; letter-spacing: 1px;
}}
QLineEdit:focus {{ border: 1px solid {ACCENT_BASE}; }}

QPushButton {{
    background-color: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 13px; font-weight: 700; font-size: 12px;
    font-family: {MONO_FAMILY}; letter-spacing: 2px;
}}
QPushButton:hover {{ border: 1px solid {ACCENT_BASE}; color: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background-color: {BORDER}; }}
QPushButton:checked {{ background-color: {ACCENT_DIM}; border: 1px solid {ACCENT}; color: {TEXT}; }}
QPushButton#danger:hover {{ border: 1px solid {BAD}; color: {BAD}; }}

QSplitter::handle {{ background-color: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {ACCENT_DIM}; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_LIGHT}; border-radius: 4px; min-height: 26px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_LIGHT}; border-radius: 4px; min-width: 26px; }}

QToolTip {{
    background-color: {BG_CARD}; color: {ACCENT}; border: 1px solid {ACCENT_DIM};
    padding: 4px 8px; font-family: {MONO_FAMILY};
}}
QMenu {{ background-color: {BG_CARD}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background-color: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QMessageBox {{ background-color: {BG_CARD}; }}

/* === sinematik HUD (ui/hud) === */
QFrame#hudTopBar {{ background: transparent; border-bottom: 1px solid {BORDER}; }}
QLabel#hudWordmark {{
    font-size: 20px; font-weight: 700; letter-spacing: 6px; color: {ACCENT};
}}
QLabel#hudTag {{
    color: {GOLD_DIM}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 3px;
}}
QToolButton#hudChip {{
    background: transparent; border: 1px solid {BORDER_LIGHT}; border-radius: 2px;
    padding: 4px 6px; font-family: {MONO_FAMILY}; font-size: 10px; font-weight: 700;
    letter-spacing: 1px; color: {TEXT_DIM};
}}
QToolButton#hudChip:hover {{ border: 1px solid {ACCENT_DIM}; color: {ACCENT_HOVER}; }}
QToolButton#hudChip:checked {{
    background-color: rgba(52, 227, 240, 30); border: 1px solid {ACCENT}; color: {ACCENT};
}}
QToolButton#hudChip:disabled {{ color: {TEXT_FAINT}; border: 1px solid {BORDER}; }}
QToolButton#hudChipDanger {{
    background: transparent; border: 1px solid {BORDER_LIGHT}; border-radius: 2px;
    padding: 4px 7px; font-family: {MONO_FAMILY}; font-size: 10px; font-weight: 700; color: {TEXT_DIM};
}}
QToolButton#hudChipDanger:hover {{ border: 1px solid {BAD}; color: {BAD}; }}

QLabel#hudCardIndex {{ color: {GOLD}; font-family: {MONO_FAMILY}; font-size: 9px; font-weight: 700; }}
QLabel#hudCardTitle {{
    color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 10px; font-weight: 700; letter-spacing: 3px;
}}
QLabel#hudCardMeta {{ color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 1px; }}
QToolButton#hudCardToggle {{
    background: transparent; border: none; color: {TEXT_DIM}; font-size: 10px; padding: 0 2px;
}}
QToolButton#hudCardToggle:hover {{ color: {ACCENT}; }}
QLabel#hudBig {{ font-size: 44px; font-weight: 700; color: {TEXT}; letter-spacing: 2px; }}
QLabel#hudBigSub {{ font-size: 18px; font-weight: 600; color: {ACCENT}; }}
QLabel#hudLine {{ color: {TEXT_DIM}; font-size: 13px; letter-spacing: 1px; }}
QLabel#hudLineStrong {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QLabel#hudKey {{ color: {GOLD}; font-family: {MONO_FAMILY}; font-size: 9px; font-weight: 700; letter-spacing: 2px; }}

QFrame#hudCard QPlainTextEdit#log, QFrame#hudCard QTextEdit#log {{
    background: transparent; border: none;
}}
QFrame#hudCard QTextEdit#transcript {{ background: transparent; border: none; }}

QLabel#hudCaption {{ color: {TEXT}; font-size: 17px; font-weight: 500; letter-spacing: 1px; }}
QLabel#hudState {{ font-family: {MONO_FAMILY}; font-size: 12px; font-weight: 700; letter-spacing: 8px; }}
QLabel#hudPrompt {{ color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 15px; font-weight: 700; }}
QLineEdit#commandInput {{
    background-color: {HUD_GLASS_QSS}; border: 1px solid {BORDER_LIGHT}; border-left: 2px solid {ACCENT};
    border-radius: 0; padding: 9px 12px; font-size: 13px;
}}
QLineEdit#commandInput:focus {{ border: 1px solid {ACCENT_BASE}; border-left: 2px solid {ACCENT}; }}
"""
