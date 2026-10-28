# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - JARVIS masaustu uygulamasi (onedir).

Derle:  pyinstaller --noconfirm jarvis.spec
Cikti:  dist/JARVIS/JARVIS.exe   (yaninda .env, data/, bridge/ olusur)
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "prompts"), "prompts"),
    (str(ROOT / "assets"), "assets"),
    # web konsolunun statik dosyalari (jest modulleri, yerel MediaPipe modelleri)
    (str(ROOT / "web" / "static"), "web/static"),
]
binaries = []
hiddenimports = ["winsound", "mss", "mss.windows"]

# google-genai + opencv genelde ek veri/altmodul ister
for pkg in ("google.genai", "google.api_core", "cv2"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001
        pass

hiddenimports += collect_submodules("google")

icon_file = ROOT / "assets" / "jarvis.ico"
icon = str(icon_file) if icon_file.is_file() else None

a = Analysis(
    [str(ROOT / "run_ui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # QtWebEngine dahil: icerik paneli (ui/widgets/panel_web.py) onu tembel ice aktarir
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="JARVIS",
)
