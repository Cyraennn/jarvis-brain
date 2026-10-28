"""Arayuz paleti + global stil (QSS).

Zoey OS (zoeyos.com) estetigi: saf siyah zemin, ustu hafif aydinlik cam kartlar, tek vurgu
rengi turuncu (#ff8c42 / logo #ff6d00) + orb'daki macenta. Govde yazisi Onest, etiketler
JetBrains Mono. Eski isimler geriye uyumluluk icin korunur.

Vurgu rengi kisilige gore degisir (PALETTES: JARVIS mavi, FRIDAY yesil, ULTRON kirmizi);
`apply_palette(key)` modul degiskenlerini ve QSS'i calisirken yeniden kurar. Asagidaki
turuncu degerler yalnizca tabandir, import sonunda jarvis paleti uygulanir.
"""

from __future__ import annotations

# --- palet -----------------------------------------------------------------
BG_SPACE = "#000000"       # en arka zemin
BG_MAIN = "#000000"        # ana calisma alani
BG_RIBBON = "#000000"      # ust serit / sol dikey serit
BG_SIDEBAR = "#0c0c0f"     # kenar panelleri (Zoey --panel)
BG_CARD = "#141419"        # yuzeyler (Zoey --panel-2)
BG_CARD_HOVER = "#1c1c22"
BG_INPUT = "#0b0b0e"
BG_STATUSBAR = "#000000"
BG_GLASS = "#101016"
BG_CANVAS = "#000000"      # orta tuval
# Cam yuzey (Zoey --glass-bg): ustte beyaz isik, ortada neredeyse siyah, altta hafif yansima
CARD_TOP = "#1a1a1e"
CARD_BOTTOM = "#0f0f12"
CARD_STOPS = ((0.0, "#1d1d21"), (0.3, "#0f0f12"), (0.58, "#09090b"), (1.0, "#121215"))
CANVAS_TOP = "#000000"
CANVAS_BOTTOM = "#000000"
EDGE_LIGHT = "#3a3a3f"     # yuzeylerin ust kenarindaki isik cizgisi (inset #ffffff29)
BTN_TOP = "#1a1a1f"
BTN_BOTTOM = "#0e0e11"
SHADOW = (0, 0, 0, 0)      # siyah zeminde golge gorunmez

BORDER = "#1f1f23"         # #ffffff1c siyah ustunde
BORDER_LIGHT = "#2e2e33"   # #ffffff2e
GRID = "#17171b"

ACCENT = "#ff8c42"         # Zoey turuncusu (birincil)
ACCENT_BASE = "#ff6d00"    # logo turuncusu
ACCENT_DIM = "#4a2208"     # #ff6d0047 siyah ustunde
STATE_IDLE = "#ff6d00"     # "HAZIR" durum yazisi (Zoey .hc-status)
ACCENT_HOVER = "#ffb07a"   # Zoey --o-ember
ACCENT_INK = "#1a0900"     # turuncu dolgu ustundeki koyu metin
GOLD = "#ffd166"           # uyari (ikincil)
GOLD_DIM = "#5e4c22"
MYSTIC = "#e91e8c"         # orb macentasi (ucuncul)
MYSTIC_DIM = "#4d0a2e"

SPEAK = ACCENT             # model konusurken
GOOD = "#10b981"
WARN = "#ffd166"
BAD = "#ef4444"

TEXT = "#f0f0f0"           # #fffffff0
TEXT_DIM = "#9e9e9e"       # #ffffff9e
TEXT_MUTED = "#9e9e9e"
TEXT_FAINT = "#7a7a80"     # kart zemininde okunur kalsin (~4.5:1)

USER_COLOR = "#d6d6db"
JARVIS_COLOR = "#ffb07a"

# Departman dugum renkleri (Zoey orb temalari; sirayla dagitilir)
DEPT_COLORS = ("#ff8c42", "#e91e8c", "#48cae4", "#ffd166", "#8338ec", "#06d6a0")

# --- HUD kartlari (ui/hud) -------------------------------------------------
HUD_GLASS = (16, 16, 22, 255)       # kart zemini (RGBA; QPainter'da kullanilir)
HUD_GLASS_QSS = "#101016"
HUD_EDGE = BORDER                   # kart kenari
HUD_TICK = ACCENT                   # kart basligi isareti
CARD_RADIUS = 12.0

# --- geriye uyumlu takma adlar -------------------------------------------
BG_DEEP = BG_MAIN
BG_PANEL = BG_SIDEBAR
BG_PANEL_ALT = BG_CARD

GLOW_EDGE = "rgba(255, 109, 0, 77)"   # odak/hover kenari (vurgu rengi, %30)
GLOW_FILL = "rgba(255, 140, 66, 26)"  # secili chip dolgusu (vurgu rengi, %10)

# --- kisilik paletleri (core/personas.py; HUD'daki EKIPLER cipleri) ---------------
# Her anahtar ayni adli modul degiskenini ezer; "glow" (r, g, b) GLOW_* degerlerini,
# "orb" orb parcacik renklerini (ekvator, kutup), "effect" arka plan efektini verir.
_NEUTRAL_CARD = {
    "CARD_TOP": "#1a1a1e", "CARD_BOTTOM": "#0f0f12",
    "CARD_STOPS": ((0.0, "#1d1d21"), (0.3, "#0f0f12"), (0.58, "#09090b"), (1.0, "#121215")),
    "BORDER": "#1f1f23", "EDGE_LIGHT": "#3a3a3f",
}
PALETTES: dict[str, dict] = {
    "jarvis": {
        **_NEUTRAL_CARD,
        "ACCENT": "#4cb4ff", "ACCENT_BASE": "#1e8fff", "ACCENT_DIM": "#0a2a4a",
        "STATE_IDLE": "#1e8fff", "ACCENT_HOVER": "#9ad3ff", "ACCENT_INK": "#001426",
        "MYSTIC": "#22e3ff", "MYSTIC_DIM": "#063a44", "JARVIS_COLOR": "#9ad3ff",
        "glow": (30, 143, 255), "orb": ("#22e3ff", "#1e8fff"), "effect": "",
    },
    "friday": {
        # daha temiz ve parlak: kartlar bir ton acik, kenarlar belirgin
        "CARD_TOP": "#202424", "CARD_BOTTOM": "#121515",
        "CARD_STOPS": ((0.0, "#252a29"), (0.3, "#141817"), (0.58, "#0d100f"), (1.0, "#171b1a")),
        "BORDER": "#233029", "EDGE_LIGHT": "#4a5a53",
        "ACCENT": "#2ee59d", "ACCENT_BASE": "#14c47f", "ACCENT_DIM": "#0a3d2a",
        "STATE_IDLE": "#14c47f", "ACCENT_HOVER": "#9ff5d0", "ACCENT_INK": "#00170d",
        "MYSTIC": "#b6ffe4", "MYSTIC_DIM": "#1d4a3c", "JARVIS_COLOR": "#9ff5d0",
        "glow": (20, 196, 127), "orb": ("#b6ffe4", "#14c47f"), "effect": "friday",
    },
    "ultron": {
        # sert ve karanlik: kartlar kizil siyah, kenarlar kor
        "CARD_TOP": "#1e1214", "CARD_BOTTOM": "#0e0809",
        "CARD_STOPS": ((0.0, "#221315"), (0.3, "#100909"), (0.58, "#080505"), (1.0, "#140b0c")),
        "BORDER": "#2a1416", "EDGE_LIGHT": "#4a2226",
        "ACCENT": "#ff4d4d", "ACCENT_BASE": "#e01b1b", "ACCENT_DIM": "#4a0b0b",
        "STATE_IDLE": "#e01b1b", "ACCENT_HOVER": "#ff9a8a", "ACCENT_INK": "#1a0000",
        "MYSTIC": "#ff8a1e", "MYSTIC_DIM": "#4a2406", "JARVIS_COLOR": "#ff9a8a",
        "glow": (224, 27, 27), "orb": ("#ff8a1e", "#e01b1b"), "effect": "ultron",
    },
}

# kisilige gore arayuz metinleri ("Hey JARVIS" uyandirma kelimesi sabit kalir)
BRANDING: dict[str, dict[str, str]] = {
    "jarvis": {"name": "JARVIS", "wordmark": "JARVIS", "tag": "KİŞİSEL ASİSTAN",
               "greeting": "“Emrinizdeyim efendim.”",
               "placeholder": "JARVIS'e yaz — Enter ile canlı oturuma gönder"},
    "friday": {"name": "FRIDAY", "wordmark": "FRIDAY", "tag": "OPERASYON ASİSTANI",
               "greeting": "“Hazırım patron, ne yapıyoruz?”",
               "placeholder": "FRIDAY'e yaz — Enter ile canlı oturuma gönder"},
    "ultron": {"name": "ULTRON", "wordmark": "ULTRON", "tag": "BAĞIMSIZ ZEKÂ",
               "greeting": "“Yine mi sen… Söyle bakalım.”",
               "placeholder": "ULTRON'a yaz — itiraz edecek ama yapacak"},
}

PERSONA = "jarvis"   # apply_palette ile degisir
EFFECT = ""          # "" | "friday" | "ultron" (HudBackdrop katmani)
ORB_COLORS = ("#e91e8c", "#ff6d00")

FONT_FAMILY = '"Onest", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif'
MONO_FAMILY = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'


# str.format sablonu (f-string ile ayni {{ }} kacisi); build_qss() guncel paletle doldurur.
_QSS_TEMPLATE = """
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
    color: {TEXT_FAINT}; font-size: 10px; letter-spacing: 3px; font-family: {MONO_FAMILY};
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
QLineEdit:focus {{ border: 1px solid {GLOW_EDGE}; }}

QPushButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_TOP}, stop:1 {BTN_BOTTOM});
    border: 1px solid {BORDER}; border-top-color: {EDGE_LIGHT}; border-radius: 8px;
    padding: 7px 14px; font-weight: 700; font-size: 12px;
    font-family: {FONT_FAMILY}; letter-spacing: 1px;
}}
QPushButton:hover {{ border: 1px solid {GLOW_EDGE}; color: {ACCENT_HOVER}; }}
QPushButton:pressed {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_BOTTOM}, stop:1 {BTN_TOP});
    border-top-color: {BG_RIBBON};
}}
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

/* === Komuta HUD (ui/hud) === */
QFrame#hudTopBar {{ background-color: {BG_RIBBON}; border-bottom: 1px solid #141417; }}
QLabel#hudWordmark {{
    font-family: {MONO_FAMILY}; font-size: 15px; font-weight: 700; letter-spacing: 3px; color: {ACCENT_BASE};
}}
QLabel#hudWordmarkAccent {{
    font-family: {MONO_FAMILY}; font-size: 7px; font-weight: 700; color: {ACCENT_BASE}; padding-bottom: 9px;
}}
QLabel#hudTag {{
    color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 2px;
}}
QToolButton#hudChip {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_TOP}, stop:1 {BTN_BOTTOM});
    border: 1px solid {BORDER}; border-top-color: {EDGE_LIGHT}; border-radius: 11px;
    padding: 4px 7px; font-family: {MONO_FAMILY}; font-size: 10px; font-weight: 700;
    letter-spacing: 0px; color: {TEXT_DIM};
}}
QToolButton#hudChip:hover {{ border: 1px solid {BORDER_LIGHT}; color: {TEXT}; }}
QToolButton#hudChip:pressed {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_BOTTOM}, stop:1 {BTN_TOP});
}}
QToolButton#hudChip:checked {{
    background-color: {GLOW_FILL};
    border: 1px solid {GLOW_EDGE}; color: {ACCENT};
}}
QToolButton#hudChip::menu-button {{ border: none; background: transparent; width: 12px; }}
QToolButton#hudChip:disabled {{ color: {TEXT_FAINT}; border: 1px solid {BORDER}; }}
QToolButton#hudChipDanger {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_TOP}, stop:1 {BTN_BOTTOM});
    border: 1px solid {BORDER}; border-top-color: {EDGE_LIGHT}; border-radius: 11px;
    padding: 4px 7px; font-family: {MONO_FAMILY}; font-size: 10px; font-weight: 700; color: {TEXT_DIM};
}}
QToolButton#hudChipDanger:hover {{ border: 1px solid {BAD}; color: {BAD}; }}

QScrollArea#hudColumn {{ background: transparent; border: none; }}
QWidget#hudColumnBody {{ background: transparent; }}
QLabel#hudCanvasSub {{ color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 3px; }}

QLabel#hudCardTitle {{
    color: {TEXT}; font-family: {FONT_FAMILY}; font-size: 11px; font-weight: 700; letter-spacing: 2px;
}}
QLabel#hudCardMeta {{ color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 1px; }}
QToolButton#hudCardToggle {{
    background: transparent; border: none; color: {TEXT_DIM}; font-size: 10px; padding: 0 2px;
}}
QToolButton#hudCardToggle:hover {{ color: {ACCENT}; }}
QLabel#hudBig {{ font-size: 26px; font-weight: 700; color: {ACCENT}; font-family: {MONO_FAMILY}; }}
QLabel#hudBigSub {{ font-size: 26px; font-weight: 700; color: {ACCENT}; font-family: {MONO_FAMILY}; }}
QLabel#hudCount {{ font-size: 30px; font-weight: 700; color: {ACCENT}; font-family: {MONO_FAMILY}; }}
QLabel#hudLine {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#hudLineStrong {{ color: {TEXT}; font-size: 12px; font-weight: 600; }}
QLabel#hudKey {{
    color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 9px; font-weight: 700; letter-spacing: 2px;
}}
QLabel#hudTicker {{
    color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 10px; letter-spacing: 1px;
    padding: 4px 12px;
}}

QPushButton#quickTile {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_TOP}, stop:1 {BTN_BOTTOM});
    border: 1px solid {BORDER}; border-top-color: {EDGE_LIGHT}; border-radius: 10px;
    padding: 8px 9px; text-align: left; font-family: {FONT_FAMILY}; font-size: 11px;
    font-weight: 600; letter-spacing: 0px; color: {TEXT};
}}
QPushButton#quickTile:hover {{ border: 1px solid {GLOW_EDGE}; color: {ACCENT_HOVER}; }}
QPushButton#quickTile:pressed {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_BOTTOM}, stop:1 {BTN_TOP});
    border-top-color: {BG_RIBBON}; padding-top: 9px; padding-bottom: 7px;
}}

QLabel#routineTime {{ color: {TEXT_DIM}; font-family: {MONO_FAMILY}; font-size: 10px; }}
QLabel#routineName {{ color: {TEXT}; font-size: 12px; }}
QLabel#routineState {{ color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 1px; }}
QLabel#routineStateOn {{ color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 9px; letter-spacing: 1px; }}

QFrame#hudCard QTreeWidget::item, QFrame#hudCard QListWidget::item {{
    padding: 5px 4px; border-radius: 0; border-bottom: 1px solid {BORDER};
}}

QFrame#hudCard QPlainTextEdit#log, QFrame#hudCard QTextEdit#log {{
    background: transparent; border: none;
}}
QFrame#hudCard QTextEdit#transcript {{ background: transparent; border: none; }}

QFrame#contentPanel {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {CARD_TOP}, stop:1 {CARD_BOTTOM});
    border: 1px solid {HUD_EDGE}; border-top-color: {EDGE_LIGHT}; border-radius: 12px;
}}
QFrame#panelHead {{ background: transparent; border: none; border-bottom: 1px solid {HUD_EDGE}; }}
QLabel#panelTag {{ color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 10px; font-weight: 700; letter-spacing: 2px; }}
QLabel#panelTitle {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QLabel#panelSub {{ color: {TEXT_FAINT}; font-family: {MONO_FAMILY}; font-size: 10px; letter-spacing: 1px; }}
QLabel#panelMessage {{ color: {TEXT_DIM}; font-size: 15px; padding: 24px; }}
QPlainTextEdit#panelText {{
    background-color: {BG_INPUT}; border: none; color: {TEXT}; padding: 14px;
    font-family: {MONO_FAMILY}; font-size: 13px;
}}
QScrollArea#panelScroll {{ background: transparent; border: none; }}
QWidget#panelScrollBody {{ background: transparent; }}
QFrame#newsItem {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BTN_TOP}, stop:1 {BTN_BOTTOM});
    border: 1px solid {BORDER}; border-top-color: {EDGE_LIGHT}; border-radius: 10px;
}}
QFrame#newsItem:hover {{ border: 1px solid {ACCENT_BASE}; }}
QLabel#newsIndex {{ color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 12px; font-weight: 700; }}
QLabel#newsTitle {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QLabel#newsMeta {{ color: {TEXT_DIM}; font-family: {MONO_FAMILY}; font-size: 10px; letter-spacing: 1px; }}
QLabel#weatherTemp {{ color: {ACCENT}; font-size: 64px; font-weight: 700; }}
QLabel#weatherCond {{ color: {TEXT}; font-size: 20px; font-weight: 600; }}
QLabel#weatherDay {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QTextBrowser#panelInfo {{
    background: transparent; border: none; color: {TEXT}; font-size: 14px;
    selection-background-color: {ACCENT_DIM};
}}
QLabel#spotifyCover {{ background-color: {BG_CARD}; border: 1px solid {HUD_EDGE}; color: {ACCENT_DIM}; font-size: 72px; }}
QLabel#spotifyTrack {{ color: {TEXT}; font-size: 22px; font-weight: 700; }}
QLabel#spotifyArtist {{ color: {TEXT_DIM}; font-size: 14px; }}
QProgressBar#spotifyBar {{ background-color: {BORDER}; border: none; }}
QProgressBar#spotifyBar::chunk {{ background-color: {ACCENT}; }}
QToolButton#spotifyBtn {{
    background: transparent; border: 1px solid {BORDER_LIGHT}; border-radius: 2px;
    padding: 7px 18px; font-size: 13px; font-weight: 700; letter-spacing: 1px; color: {TEXT};
}}
QToolButton#spotifyBtn:hover {{ border: 1px solid {ACCENT}; color: {ACCENT}; }}

QLabel#hudCaption {{ color: {TEXT_DIM}; font-size: 14px; }}
QLabel#hudState {{ font-family: {MONO_FAMILY}; font-size: 11px; font-weight: 700; letter-spacing: 6px; }}
QLabel#hudPrompt {{ color: {ACCENT}; font-family: {MONO_FAMILY}; font-size: 15px; font-weight: 700; }}
QLineEdit#commandInput {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17171b, stop:0.4 #0d0d10, stop:1 #111114);
    border: 1px solid {BORDER}; border-top-color: {EDGE_LIGHT}; border-radius: 19px;
    padding: 9px 18px; font-family: {FONT_FAMILY}; font-size: 13px; letter-spacing: 0px;
}}
QLineEdit#commandInput:focus {{ border: 1px solid {GLOW_EDGE}; }}
"""


def build_qss() -> str:
    """Guncel modul degiskenleriyle global stil sayfasi."""
    return _QSS_TEMPLATE.format(**globals())


def branding(key: str | None = None) -> dict[str, str]:
    return BRANDING.get(key or PERSONA, BRANDING["jarvis"])


def apply_palette(key: str) -> str:
    """Kisilik paletini modul degiskenlerine uygular ve QSS'i yeniden uretir.

    Renkleri olusturulurken yakalayan widget'lar `refresh_theme()` ile tazelenir
    (bkz. HudWindow.apply_persona_theme). Bilinmeyen anahtar -> jarvis. Uygulanan anahtari doner.
    """
    global SPEAK, HUD_TICK, HUD_EDGE, DEPT_COLORS, GLOW_EDGE, GLOW_FILL
    global PERSONA, EFFECT, ORB_COLORS, QSS
    key = key if key in PALETTES else "jarvis"
    pal = PALETTES[key]
    g = globals()
    for name, value in pal.items():
        if name.isupper():
            g[name] = value
    r, gr, b = pal["glow"]
    GLOW_EDGE = f"rgba({r}, {gr}, {b}, 77)"
    GLOW_FILL = f"rgba({r}, {gr}, {b}, 26)"
    SPEAK = g["ACCENT"]
    HUD_TICK = g["ACCENT"]
    HUD_EDGE = g["BORDER"]
    DEPT_COLORS = (g["ACCENT"], g["MYSTIC"], *_DEPT_REST)
    PERSONA, EFFECT, ORB_COLORS = key, pal["effect"], pal["orb"]
    QSS = build_qss()
    return key


_DEPT_REST = DEPT_COLORS[2:]
QSS = build_qss()
apply_palette("jarvis")
