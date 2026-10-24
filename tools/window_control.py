"""Uygulama kapatma - NAZIK (WM_CLOSE / taskkill /IM, `/F` yok).

Onay kontrolu bu modulde degil; cagiran (ToolRunner) kullanici onayini alir.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

_IS_WIN = sys.platform == "win32"

# Dostane ad -> calistirilabilir dosya adi
_EXE_ALIASES: dict[str, str] = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "krom": "chrome.exe",
    "opera": "opera.exe",
    "opera gx": "opera.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "brave": "brave.exe",
    "spotify": "Spotify.exe",
    "notepad": "notepad.exe",
    "not defteri": "notepad.exe",
    "hesap makinesi": "CalculatorApp.exe",
    "calculator": "CalculatorApp.exe",
    "paint": "mspaint.exe",
    "discord": "Discord.exe",
    "steam": "steam.exe",
    "telegram": "Telegram.exe",
    "whatsapp": "WhatsApp.exe",
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "code": "Code.exe",
    "cursor": "Cursor.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "obsidian": "Obsidian.exe",
}

# Asla kapatilmayacak sistem / kritik surecler
_PROTECTED: set[str] = {
    "system",
    "system.exe",
    "explorer.exe",
    "dwm.exe",
    "winlogon.exe",
    "wininit.exe",
    "csrss.exe",
    "services.exe",
    "lsass.exe",
    "smss.exe",
    "svchost.exe",
    "taskmgr.exe",
    "sihost.exe",
    "ctfmon.exe",
    "fontdrvhost.exe",
    "python.exe",
    "pythonw.exe",
}


def _normalize(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def is_protected_exe(exe: str) -> bool:
    """Asla kapatilmayacak bir surec mi (sistem surecleri + CYRAEN'in kendi python'u)?"""
    return (exe or "").strip().lower() in _PROTECTED


def exe_for(name: str) -> str:
    """Dostane ad -> bilinen exe adi (yoksa bos string)."""
    return _EXE_ALIASES.get(_normalize(name), "")


def resolve_close_target(name: str) -> dict[str, Any]:
    """Dostane adi kapatilacak exe adina cevirir."""
    n = _normalize(name)
    if not n:
        return {"ok": False, "error": "Uygulama adi bos."}
    exe = _EXE_ALIASES.get(n)
    if not exe:
        exe = name.strip() if name.strip().lower().endswith(".exe") else f"{name.strip()}.exe"
    if exe.lower() in _PROTECTED:
        return {"ok": False, "error": f"'{exe}' korumali bir surec, kapatilamaz."}
    return {"ok": True, "exe": exe, "label": name.strip()}


def close_application(target: dict[str, Any]) -> dict[str, Any]:
    """`resolve_close_target` ciktisini alir, uygulamayi nazikce kapatir."""
    exe = target["exe"]
    label = target.get("label", exe)

    if not _IS_WIN:
        result = subprocess.run(["pkill", "-f", exe], capture_output=True, check=False)
        if result.returncode == 0:
            return {"status": "kapatildi", "exe": exe}
        return {"error": f"'{label}' kapatilamadi."}

    # /F YOK => GUI uygulamalarina WM_CLOSE gonderir (kaydetme sorusu cikabilir)
    result = subprocess.run(
        ["taskkill", "/IM", exe],
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode == 0:
        return {"status": "kapatma istegi gonderildi", "exe": exe}
    if "not found" in output or "bulunam" in output or "not running" in output:
        return {"error": f"'{label}' su an calismyor gibi gorunuyor."}
    if "access is denied" in output or "erisim engellendi" in output:
        return {"error": f"'{label}' kapatilamadi: erisim engellendi (yonetici gerekebilir)."}
    return {"error": f"'{label}' kapatilamadi."}
