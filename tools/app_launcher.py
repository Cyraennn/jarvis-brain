"""Bilgisayarda uygulama / web sitesi / dosya-klasor acma.

Windows odakli (ShellExecute = os.startfile: PATH, "App Paths" kaydi, dosya
iliskileri ve protokoller dahil), ancak macOS ve Linux'ta da calisir.

Katmanli cozumleme sirasi (open_application):
    1. Bilinen takma adlar (not defteri, hesap makinesi, ayarlar, ...)
    2. Dogrudan ShellExecute / PATH / App Paths
    3. Baslat Menusu + Masaustu kisayol (.lnk / .url) bulanik aramasi
    4. Bulunamazsa oneri listesi
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from loguru import logger

from tools.keyboard_input import (
    SEARCH_HOSTS,
    close_search,
    get_foreground_window,
    search_and_open,
    snapshot_windows,
)

_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

_WIN_ALIASES: dict[str, str] = {
    "notepad": "notepad.exe",
    "not defteri": "notepad.exe",
    "hesap makinesi": "calc.exe",
    "hesap makinasi": "calc.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "komut istemi": "cmd.exe",
    "powershell": "powershell.exe",
    "windows terminal": "wt.exe",
    "terminal": "wt.exe",
    "explorer": "explorer.exe",
    "dosya gezgini": "explorer.exe",
    "gorev yoneticisi": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "kayit defteri": "regedit.exe",
    "ayarlar": "ms-settings:",
    "windows ayarlari": "ms-settings:",
    "settings": "ms-settings:",
    "denetim masasi": "control.exe",
    "control panel": "control.exe",
    "snipping tool": "snippingtool.exe",
    "ekran alintisi": "ms-screenclip:",
}

_MAC_ALIASES: dict[str, str] = {
    "terminal": "Terminal",
    "safari": "Safari",
    "notes": "Notes",
    "calculator": "Calculator",
    "finder": "Finder",
}

# Kisa/gunluk isimleri kisayol adlarina cevirir (kisayol aramasindan once uygulanir).
_QUERY_ALIASES: dict[str, str] = {
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "vs": "visual studio code",
    "kod": "visual studio code",
    "chrome": "google chrome",
    "krom": "google chrome",
    "opera": "opera gx",
    "edge": "microsoft edge",
    "photoshop": "adobe photoshop",
    "premiere": "adobe premiere pro",
    "after effects": "adobe after effects",
    "visual studio": "visual studio 2022",
    "android": "android studio",
    "office word": "word",
    "office excel": "excel",
}

_SITE_SHORTCUTS: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "spotify": "https://open.spotify.com",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "instagram": "https://www.instagram.com",
    "netflix": "https://www.netflix.com",
    "google": "https://www.google.com",
    "maps": "https://maps.google.com",
    "translate": "https://translate.google.com",
}


# --------------------------------------------------------------------- yardimci

def _normalize(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _launch_native(target: str) -> None:
    """Hedefi isletim sistemi kabuguyla acar (engellemez)."""
    if _IS_WIN:
        os.startfile(target)  # type: ignore[attr-defined]
    elif _IS_MAC:
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


@lru_cache(maxsize=1)
def _shortcut_index() -> dict[str, Path]:
    """Baslat Menusu + Masaustu kisayollarini normalize isimden yola esler (Windows)."""
    index: dict[str, Path] = {}
    if not _IS_WIN:
        return index
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive/Desktop",
        Path(os.environ.get("PUBLIC", "")) / "Desktop",
    ]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for pattern in ("*.lnk", "*.url"):
                for path in root.rglob(pattern):
                    index.setdefault(_normalize(path.stem), path)
        except OSError:
            continue
    return index


def _match_shortcut(query: str) -> tuple[str, Path] | None:
    index = _shortcut_index()
    if not index:
        return None
    q = _normalize(query)
    q = _QUERY_ALIASES.get(q, q)
    if len(q) < 2:
        return None

    if q in index:
        return q, index[q]

    # bosluksuz karsilastirma (orn. "not defteri" <-> "notdefteri")
    qns = q.replace(" ", "")
    despaced = {k.replace(" ", ""): k for k in index}
    if qns in despaced:
        key = despaced[qns]
        return key, index[key]

    for candidates in (
        [k for k in index if k.startswith(q)],
        [k for k, ns in ((k, k.replace(" ", "")) for k in index) if ns.startswith(qns)],
        [k for k in index if q in k],
    ):
        if candidates:
            best = min(candidates, key=len)
            return best, index[best]

    # bulanik esleme - kisa sorgularda yanlis pozitifi onlemek icin siki
    close = get_close_matches(q, list(index), n=3, cutoff=0.8)
    for cand in close:
        if cand[:1] == q[:1] and abs(len(cand) - len(q)) <= 4:
            return cand, index[cand]
    return None


def _suggestions(query: str, limit: int = 8) -> list[str]:
    index = _shortcut_index()
    if not index:
        return []
    q = _normalize(query)
    ranked = get_close_matches(q, list(index), n=limit, cutoff=0.3)
    titles = [index[k].stem for k in ranked]
    if not titles and q:
        titles = sorted({index[k].stem for k in index if k[:1] == q[:1]})[:limit]
    return titles


# ------------------------------------------------------------------------ tools

def _search_mode_settings() -> tuple[bool, float]:
    """(arama_ile_ac, karakter_gecikmesi) - ayar okunamazsa guvenli varsayilan."""
    try:
        from config.settings import get_settings

        cfg = get_settings()
        return bool(cfg.open_apps_via_search), float(cfg.search_type_delay)
    except Exception:  # noqa: BLE001
        return True, 0.06


def _search_text_for(name: str, q: str) -> str:
    """Aramaya yazilacak en isabetli metin: takma ad -> kisayolun gercek adi -> ham ad."""
    if q in _WIN_ALIASES:
        typed = _WIN_ALIASES[q]
    else:
        match = _match_shortcut(name)
        typed = Path(match[1]).stem if match else _QUERY_ALIASES.get(q, name)
    return typed[:-4] if typed.lower().endswith(".exe") else typed


def _confirm_launched(
    before: dict[int, tuple[str, str, int]], before_fg: int, timeout: float = 6.0
) -> str | None:
    """Arama + Enter sonrasi bir uygulama penceresi GERCEKTEN acildi/one geldi mi?

    Yeni bir ust-duzey pencere belirmesi ya da on planin (arama paneli / JARVIS disinda)
    baska bir pencereye gecmesi basari sayilir. Basliklari dondurur, yoksa None.
    """
    own = os.getpid()
    end = time.monotonic() + timeout
    while True:
        snap = snapshot_windows()
        for hwnd, (title, exe, pid) in snap.items():
            if pid == own or exe in SEARCH_HOSTS:
                continue
            if hwnd not in before:
                return title or exe
        fg = get_foreground_window()
        info = snap.get(fg)
        if info and fg != before_fg and info[2] != own and info[1] not in SEARCH_HOSTS:
            return info[0] or info[1]
        if time.monotonic() >= end:
            return None
        time.sleep(0.25)


def open_application(name: str) -> dict[str, Any]:
    """Adiyla bir masaustu uygulamasini baslatir.

    Ayara gore ya Windows arama cubuguna harf harf yazarak (varsayilan) ya da
    dogrudan (sistem takma adi -> Baslat/Masaustu kisayolu -> kabuk/PATH) acar.
    """
    name = (name or "").strip()
    if not name:
        return {"error": "Uygulama adi bos."}
    q = _normalize(name)

    fallback_note: str | None = None
    via_search, per_char = _search_mode_settings()
    if via_search and _IS_WIN:
        # takma ad / kisayolun gercek adi ile ara ki sonuc isabetli olsun
        typed = _search_text_for(name, q)
        # URI / dosya yolu iceren hedefler aramaya yazilamaz -> dogrudan acmaya birak
        if ":" not in typed and "\\" not in typed and "/" not in typed:
            before = snapshot_windows()
            before_fg = get_foreground_window()
            result = search_and_open(typed, submit=True, per_char=per_char)
            result.setdefault("matched", name)
            if "error" not in result:
                window = _confirm_launched(before, before_fg)
                if window:
                    result["verified"] = True
                    result["window"] = window
                    return result
                logger.warning(f"'{name}' aramayla acildi ama pencere dogrulanamadi; dogrudan aciliyor")
                fallback_note = "arama sonucu dogrulanamadi, dogrudan acildi"
            else:
                logger.warning(f"arama yolu basarisiz ({result['error']}); dogrudan aciliyor")
                fallback_note = "arama yolu basarisiz, dogrudan acildi"
            close_search()  # acik kalmis arama panelini kapat
            time.sleep(0.3)

    # macOS: 'open -a' cogu durumu tek basina cozer
    if _IS_MAC:
        target = _MAC_ALIASES.get(q, name)
        result = subprocess.run(["open", "-a", target], capture_output=True, check=False)
        if result.returncode == 0:
            return {"status": "acildi", "matched": target, "target": target}
        return {"error": f"'{name}' acilamadi.", "suggestions": _suggestions(name)}

    if not _IS_WIN:  # Linux
        exe = shutil.which(name)
        if exe:
            subprocess.Popen([exe])
            return {"status": "acildi", "matched": name, "target": exe}
        return {"error": f"'{name}' PATH uzerinde bulunamadi."}

    # --- Windows: sirali aday listesi
    candidates: list[tuple[str, str]] = []
    if q in _WIN_ALIASES:
        candidates.append(("alias", _WIN_ALIASES[q]))

    match = _match_shortcut(name)
    if match is not None:
        candidates.append(("shortcut", str(match[1])))

    candidates.append(("shell", name))
    if "." not in name and ":" not in name:
        candidates.append(("shell", f"{name}.exe"))

    tried: list[str] = []
    for via, target in candidates:
        if target in tried:
            continue
        tried.append(target)
        try:
            _launch_native(target)
            label = Path(target).stem if via == "shortcut" else name
            out = {"status": "acildi", "matched": label, "target": target, "via": via}
            if fallback_note:
                out["note"] = fallback_note
            return out
        except OSError:
            continue

    return {
        "error": f"'{name}' adinda bir uygulama bulunamadi.",
        "suggestions": _suggestions(name),
    }


def _browser_type_settings() -> tuple[bool, float, float]:
    """(tarayiciya_yaz, karakter_gecikmesi, acilis_beklemesi)."""
    try:
        from config.settings import get_settings

        cfg = get_settings()
        return (
            bool(cfg.type_in_browser),
            float(cfg.browser_type_delay),
            float(cfg.browser_open_delay),
        )
    except Exception:  # noqa: BLE001
        return True, 0.07, 2.4


def open_website(target: str) -> dict[str, Any]:
    """Bir web sitesini varsayilan tarayicida acar. URL, alan adi veya arama sorgusu kabul eder.

    Ayar acikken tarayici adres/arama cubuguna HARF HARF yazar (adim adim gorunur).
    """
    target = (target or "").strip()
    if not target:
        return {"error": "Adres bos."}

    low = _normalize(target)
    if low in _SITE_SHORTCUTS:
        url = _SITE_SHORTCUTS[low]
        to_type = url.split("://", 1)[-1].removeprefix("www.")
    elif target.lower().startswith(("http://", "https://")):
        url = target
        to_type = target
    elif " " not in target and "." in target:
        url = "https://" + target
        to_type = target
    else:  # arama sorgusu
        url = "https://www.google.com/search?q=" + quote_plus(target)
        to_type = target

    type_mode, per_char, open_delay = _browser_type_settings()
    if type_mode and _IS_WIN:
        from tools.keyboard_input import type_in_browser

        result = type_in_browser(to_type, submit=True, per_char=per_char, open_delay=open_delay)
        result.setdefault("url", url)
        if "error" not in result:
            return result
        # Yazma yolu basarisiz (tarayici on plana gelmedi / odak kayboldu): dogrudan ac
        logger.warning(f"tarayiciya yazma basarisiz ({result['error']}); dogrudan aciliyor")
        try:
            _launch_native(url)
            return {"status": "acildi", "url": url, "via": "dogrudan",
                    "note": "adres cubuguna yazma basarisiz oldu, dogrudan acildi"}
        except OSError as exc:
            return {"error": f"Acilamadi: {exc}", "url": url}

    try:
        _launch_native(url)
        return {"status": "acildi", "url": url}
    except OSError as exc:
        return {"error": f"Acilamadi: {exc}"}


def _find_chromium_browser() -> str | None:
    """Kiosk/app-mode penceresi acabilecek bir Chrome/Edge kurulumu arar."""
    candidates: list[str] = []
    if _IS_WIN:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            rf"{pf}\Google\Chrome\Application\chrome.exe",
            rf"{pf86}\Google\Chrome\Application\chrome.exe",
            rf"{local}\Google\Chrome\Application\chrome.exe" if local else "",
            rf"{pf}\Microsoft\Edge\Application\msedge.exe",
            rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
        ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_gesture_hud() -> dict[str, Any]:
    """El-jesti kontrollu 3D HUD'u (webcam + jest kontrolu) kendi penceresinde acar.

    Web konsolu (`web_console_enabled`) uzerinden `/hud` sayfasini, mumkunse
    Chrome/Edge'in app-mode'unda (adres cubugu/sekmesi olmayan, siyah-zemin
    tam ekrana yakin bir pencere) acar; bulunamazsa varsayilan tarayicida
    normal bir sekme olarak acilir.
    """
    from config.settings import get_settings

    cfg = get_settings()
    if not cfg.web_console_enabled:
        return {"error": "Web konsolu kapali (ayar: web_console_enabled)."}

    url = f"http://127.0.0.1:{cfg.web_console_port}/hud"
    if cfg.web_console_token:
        url += f"?key={cfg.web_console_token}"

    browser = _find_chromium_browser()
    if browser:
        try:
            subprocess.Popen(
                [browser, f"--app={url}", "--window-size=1440,900", "--new-window"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return {"status": "acildi", "mode": "pencere", "url": url}
        except OSError as exc:
            logger.warning(f"Jest HUD penceresi acilamadi ({browser}): {exc!r}")

    import webbrowser

    webbrowser.open(url, new=1)
    return {"status": "acildi", "mode": "tarayici sekmesi", "url": url}


class StarkTeamWindow:
    """Stark Ekibi sayfasini (/ekip) kendi uygulama penceresinde acar/kapatir.

    Ayri bir tarayici profili (--user-data-dir) kullanilir: boylece pencere kullanicinin
    acik Chrome/Edge'ine katilmaz, kendi surecinde calisir ve ayni dugmeyle kapatilabilir.
    Mikrofon izni bu profilde bir kez verilir ve hatirlanir.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    def is_open(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def open(self) -> dict[str, Any]:
        from config.settings import APP_DIR, get_settings

        if self.is_open():
            return {"status": "zaten acik"}
        cfg = get_settings()
        if not cfg.web_console_enabled:
            return {"error": "Web konsolu kapali (ayar: web_console_enabled)."}
        url = f"http://127.0.0.1:{cfg.web_console_port}/ekip"
        if cfg.web_console_token:
            url += f"?key={quote_plus(cfg.web_console_token)}"

        browser = _find_chromium_browser()
        if not browser:
            import webbrowser

            webbrowser.open(url, new=1)
            return {"status": "acildi", "mode": "tarayici sekmesi", "closable": False}
        profile = APP_DIR / "data" / "ekip_browser"
        profile.mkdir(parents=True, exist_ok=True)
        try:
            self._proc = subprocess.Popen(
                [browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1100,900",
                 "--no-first-run", "--no-default-browser-check"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return {"error": f"Pencere acilamadi: {exc}"}
        return {"status": "acildi", "mode": "pencere", "closable": True}

    def close(self) -> dict[str, Any]:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return {"status": "zaten kapali"}
        try:
            if _IS_WIN:  # tarayici alt surecleriyle birlikte (yalnizca bu profilin agaci)
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(f"Stark Ekibi penceresi kapatilamadi: {exc!r}")
            return {"error": str(exc)}
        return {"status": "kapatildi"}


def open_path(path: str) -> dict[str, Any]:
    """Bir dosyayi (varsayilan uygulamayla) veya klasoru (dosya gezgininde) acar."""
    path = (path or "").strip().strip('"')
    if not path:
        return {"error": "Yol bos."}
    resolved = Path(path).expanduser()
    if not resolved.exists():
        return {"error": f"Yol bulunamadi: {resolved}"}
    try:
        _launch_native(str(resolved))
        return {
            "status": "acildi",
            "path": str(resolved),
            "type": "dir" if resolved.is_dir() else "file",
        }
    except OSError as exc:
        return {"error": f"Acilamadi: {exc}"}
