"""Uygulamayla gelen HUD fontlarini (assets/fonts, OFL) Qt'ye yukler.

Rajdhani (baslik/metin) + JetBrains Mono (HUD etiketleri) - ikisi de Turkce karakterleri
tam destekler. Dosya yoksa sessizce sistem fontlarina (Segoe UI / Consolas) dusulur;
`ui/theme.py` font aileleri zaten bu sirayla tanimli.
"""

from __future__ import annotations

from loguru import logger
from PySide6.QtGui import QFontDatabase

from config.settings import ASSETS_DIR

FONT_DIR = ASSETS_DIR / "fonts"
_loaded: list[str] | None = None


def load_fonts() -> list[str]:
    """Fontlari bir kez yukler; yuklenen aile adlarini dondurur (QGuiApplication gerekli)."""
    global _loaded
    if _loaded is not None:
        return _loaded
    families: set[str] = set()
    if FONT_DIR.is_dir():
        for path in sorted(FONT_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0:
                logger.debug(f"Font yuklenemedi: {path.name}")
                continue
            families.update(QFontDatabase.applicationFontFamilies(font_id))
    _loaded = sorted(families)
    return _loaded
