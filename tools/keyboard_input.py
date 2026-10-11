"""Windows'ta klavye simulasyonu ile 'harf harf' yazma.

`SendInput` (ctypes) ile klavye olaylari uretir - ek bagimlilik yok, Windows'a ozel.
- search_and_open : Win+S ile arama, yaz, Enter
- type_in_browser : tarayici adres cubuguna yaz
- type_text       : odaktaki (veya adiyla bulunan) pencereye yaz  (Not Defteri, VS Code...)
"""

from __future__ import annotations

import ctypes
import functools
import sys
import threading
import time
from pathlib import Path

try:  # Linux sunucuda (VPS) bu modul import edilebilsin; Windows API'leri yalnizca _IS_WIN'de kullanilir
    from ctypes import wintypes
except (ImportError, ValueError):  # pragma: no cover - Windows disi eski Python surumleri
    wintypes = None  # type: ignore[assignment]
from typing import Any

_IS_WIN = sys.platform == "win32"

# Ayni anda birden fazla arac (ayri thread'lerde) tus/fare gonderirse girdiler
# birbirine karisir; tum girdi fonksiyonlari bu kilitle SIRALANIR.
_INPUT_LOCK = threading.RLock()

# Windows arama panelini / tarayicilari tanimak icin surec adlari
SEARCH_HOSTS = {
    "searchhost.exe", "searchapp.exe", "searchui.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe",
}
# Tarayiciyi one getirmek icin acilan hafif baslangic sayfasi
_BLANK_URL = "https://www.google.com/"
BROWSER_EXES = {
    "chrome.exe", "msedge.exe", "opera.exe", "opera_gx.exe", "firefox.exe",
    "brave.exe", "vivaldi.exe", "arc.exe",
}


class FocusLost(Exception):
    """Yazma sirasinda hedef pencere odagi kaybetti ve geri alinamadi."""

    def __init__(self, typed: int = 0) -> None:
        super().__init__("odak kayboldu")
        self.typed = typed

# --- ctypes SendInput altyapisi -------------------------------------------------
if _IS_WIN:
    ULONG_PTR = ctypes.c_size_t
    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    VK_BACK = 0x08
    VK_RETURN = 0x0D
    VK_CONTROL = 0x11
    VK_ESCAPE = 0x1B
    VK_LWIN = 0x5B
    VK_A = 0x41
    VK_L = 0x4C
    VK_S = 0x53
    VK_W = 0x57

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = (
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        )

    class _INPUTUNION(ctypes.Union):
        _fields_ = (("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT))

    class _INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))

    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.c_void_p)
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    _user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    _user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    _user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    _user32.IsIconic.argtypes = (wintypes.HWND,)
    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    VK_F24 = 0x87  # atanmamis tus: on plan kilidini gevsetmek icin zararsiz
    _user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))

    _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = (_ENUMPROC, wintypes.LPARAM)
    _user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _user32.IsWindow.argtypes = (wintypes.HWND,)
    WM_CLOSE = 0x0010

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    VK_MENU = 0x12  # ALT
    VK_SHIFT = 0x10
    VK_TAB = 0x09
    VK_D = 0x44
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    VK_MEDIA_NEXT = 0xB0
    VK_MEDIA_PREV = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_MEDIA_PLAY_PAUSE = 0xB3
    SW_RESTORE = 9

    INPUT_MOUSE = 0
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    WHEEL_DELTA = 120

    _SM_CXSCREEN = 0
    _SM_CYSCREEN = 1
    _user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    _user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    _user32.GetSystemMetrics.restype = ctypes.c_int

    _KEY_NAMES: dict[str, int] = {
        "ctrl": VK_CONTROL, "control": VK_CONTROL, "alt": VK_MENU, "shift": VK_SHIFT,
        "win": VK_LWIN, "cmd": VK_LWIN, "meta": VK_LWIN,
        "enter": VK_RETURN, "return": VK_RETURN, "tab": 0x09, "esc": VK_ESCAPE,
        "escape": VK_ESCAPE, "space": 0x20, "backspace": VK_BACK, "back": VK_BACK,
        "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
        "right": 0x27, "capslock": 0x14, "printscreen": 0x2C,
        **{f"f{i}": 0x70 + i - 1 for i in range(1, 13)},
    }

    def _send(*events: "_INPUT") -> None:
        count = len(events)
        array = (_INPUT * count)(*events)
        sent = _user32.SendInput(count, array, ctypes.sizeof(_INPUT))
        if sent != count:
            raise OSError(ctypes.get_last_error(), "SendInput basarisiz")

    def _key_event(vk: int, up: bool = False) -> "_INPUT":
        flags = KEYEVENTF_KEYUP if up else 0
        return _INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUNION(ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)),
        )

    def _char_event(char: str, up: bool = False) -> "_INPUT":
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
        return _INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUNION(
                ki=_KEYBDINPUT(wVk=0, wScan=ord(char), dwFlags=flags, time=0, dwExtraInfo=0)
            ),
        )

    def _tap(vk: int, hold: float = 0.02) -> None:
        _send(_key_event(vk))
        time.sleep(hold)
        _send(_key_event(vk, up=True))

    def _mouse_event(flags: int, data: int = 0) -> "_INPUT":
        return _INPUT(
            type=INPUT_MOUSE,
            u=_INPUTUNION(
                mi=_MOUSEINPUT(
                    dx=0, dy=0,
                    mouseData=ctypes.c_uint32(data).value,
                    dwFlags=flags, time=0, dwExtraInfo=0,
                )
            ),
        )

    def _primary_screen() -> tuple[int, int]:
        return (
            _user32.GetSystemMetrics(_SM_CXSCREEN),
            _user32.GetSystemMetrics(_SM_CYSCREEN),
        )

    def _combo(mod_vk: int, key_vk: int) -> None:
        _send(_key_event(mod_vk))
        time.sleep(0.03)
        _send(_key_event(key_vk))
        time.sleep(0.03)
        _send(_key_event(key_vk, up=True))
        time.sleep(0.03)
        _send(_key_event(mod_vk, up=True))

    def _unit_event(code: int, up: bool = False) -> "_INPUT":
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
        return _INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUNION(ki=_KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags, time=0, dwExtraInfo=0)),
        )

    def _release_modifiers() -> None:
        """Fiziksel olarak basili kalmis Shift/Ctrl/Alt/Win tuslarini birakir."""
        for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN):
            try:
                if _user32.GetAsyncKeyState(vk) & 0x8000:
                    _send(_key_event(vk, up=True))
            except OSError:
                pass

    def _foreground_exe() -> str:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _pid_exe_name(pid.value)

    def _ensure_foreground(hwnd: int) -> bool:
        """Hedef pencere hala on planda mi? Degilse bir kez geri getirmeyi dener."""
        if int(_user32.GetForegroundWindow() or 0) == int(hwnd):
            return True
        return focus_window(hwnd)

    def _type_text(text: str, per_char: float, guard_hwnd: int = 0) -> int:
        """Metni karakter karakter yazar; yazilan karakter sayisini dondurur.

        - UTF-16 vekil ciftleri (emoji vb.) dogru gonderilir.
        - \n = Enter, \t = Tab.
        - `guard_hwnd` verilirse her 8 karakterde odak kontrol edilir; kaybolur ve
          geri alinamazsa FocusLost(typed) firlatilir (yanlis pencereye yazmayi onler).
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text) > 200:  # uzun metinde saniyeler bosa harcanmasin
            per_char = min(per_char, 0.012)
        typed = 0
        for i, char in enumerate(text):
            if guard_hwnd and i % 8 == 0 and not _ensure_foreground(guard_hwnd):
                raise FocusLost(typed)
            if char == "\n":
                _tap(VK_RETURN)
            elif char == "\t":
                _tap(VK_TAB)
            else:
                raw = char.encode("utf-16-le")
                units = [int.from_bytes(raw[j : j + 2], "little") for j in range(0, len(raw), 2)]
                _send(*[_unit_event(u) for u in units])
                time.sleep(0.008)
                _send(*[_unit_event(u, up=True) for u in units])
            typed += 1
            time.sleep(max(0.0, per_char))
        return typed


def _wait_for(pred, timeout: float, step: float = 0.08) -> bool:
    """`pred()` dogru olana ya da sure dolana dek bekler."""
    end = time.monotonic() + timeout
    while True:
        try:
            if pred():
                return True
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(step)


# --- genel API ---------------------------------------------------------------

def search_and_open(
    query: str,
    submit: bool = True,
    per_char: float = 0.06,
    open_delay: float = 0.9,
) -> dict[str, Any]:
    """Windows aramasini acar, `query`'yi harf harf yazar, istege bagli Enter'lar.

    Arama paneli GERCEKTEN acildi mi dogrulanir (on plan degisti mi); acilmadiysa
    hicbir sey yazilmaz. Yazarken odak kaybolursa durur.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "Yazilacak metin bos."}
    if not _IS_WIN:
        return {"error": "Arama cubuguna yazma yalnizca Windows'ta desteklenir."}

    typed = 0
    try:
        _release_modifiers()
        prev = get_foreground_window()
        _combo(VK_LWIN, VK_S)          # Win+S -> arama
        opened = _wait_for(
            lambda: get_foreground_window() != prev or _foreground_exe() in SEARCH_HOSTS,
            2.5,
        )
        if not opened:
            _tap(VK_ESCAPE)
            return {"error": "Arama paneli acilmadi (on plan degismedi).", "search_opened": False}
        time.sleep(0.3)               # panelin girdi alanini hazirlamasi
        guard = get_foreground_window()
        _combo(VK_CONTROL, VK_A)       # varsa eski metni sec
        _tap(VK_BACK)                 # ve sil
        time.sleep(0.15)
        typed = _type_text(query, per_char, guard_hwnd=guard)
        if submit:
            time.sleep(open_delay)     # sonuclarin gelmesini bekle
            if not _ensure_foreground(guard):
                raise FocusLost(typed)
            _tap(VK_RETURN)
        return {
            "status": "arama cubugu ile acildi" if submit else "arama cubuguna yazildi",
            "typed": query,
            "submitted": submit,
            "search_opened": True,
        }
    except FocusLost as exc:
        return {"error": "Arama yazilirken odak degisti; yazma durduruldu.", "typed_chars": exc.typed}
    except OSError as exc:
        return {"error": f"Klavye simulasyonu basarisiz: {exc}"}


def type_in_search(text: str, submit: bool = True) -> dict[str, Any]:
    """Model icin arac: arama cubugunu acip verilen metni harf harf yazar."""
    return search_and_open(text, submit=submit)


def type_in_browser(
    text: str,
    submit: bool = True,
    per_char: float = 0.07,
    open_delay: float = 2.4,
) -> dict[str, Any]:
    """Varsayilan tarayiciyi acar, adres/arama cubuguna metni HARF HARF yazar.

    `text` bir URL, alan adi veya arama sorgusu olabilir; tarayici cubuga yazilani
    otomatik yorumlar (URL ise gider, degilse arama yapar). Tarayici on plana
    gelmezse (`browser_verified: False`) HICBIR sey yazilmaz.
    """
    text = (text or "").strip()
    if not text:
        return {"error": "Yazilacak metin bos."}
    if not _IS_WIN:
        return {"error": "Tarayiciya yazma yalnizca Windows'ta desteklenir."}

    import webbrowser

    typed = 0
    try:
        _release_modifiers()
        # NOT: "about:blank" KULLANMA - Windows'ta kayitli bir protokol degil, "Birlikte ac"
        # (openwith.exe) diyalogunu acar ve yazilanlar ona gider. Gercek bir https adresi ac.
        try:
            webbrowser.open_new_tab(_BLANK_URL)
        except Exception:  # noqa: BLE001
            webbrowser.open(_BLANK_URL)

        if not _wait_for(lambda: _foreground_exe() in BROWSER_EXES, max(1.5, open_delay) + 4.0):
            return {
                "error": "Tarayici on plana gelmedi; yanlis pencereye yazmamak icin durdum.",
                "browser_verified": False,
            }
        time.sleep(max(0.6, open_delay * 0.4))   # yeni sekme / adres cubugu hazir olsun
        guard = get_foreground_window()

        _combo(VK_CONTROL, VK_L)            # adres cubuguna odaklan
        time.sleep(0.35)
        _combo(VK_CONTROL, VK_A)            # varsa mevcut metni sec
        _tap(VK_BACK)
        time.sleep(0.15)

        typed = _type_text(text, per_char, guard_hwnd=guard)
        if submit:
            time.sleep(0.35)
            if not _ensure_foreground(guard):
                raise FocusLost(typed)
            _tap(VK_RETURN)
        return {
            "status": "tarayiciya yazildi",
            "typed": text,
            "submitted": submit,
            "browser_verified": True,
        }
    except FocusLost as exc:
        return {"error": "Tarayiciya yazarken odak degisti; yazma durduruldu.",
                "typed_chars": exc.typed, "browser_verified": False}
    except OSError as exc:
        return {"error": f"Klavye simulasyonu basarisiz: {exc}"}


def screen_size() -> dict[str, Any]:
    """Birincil ekranin piksel boyutlari."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    w, h = _primary_screen()
    return {"width": w, "height": h}


def _resolve_point(x: float, y: float, normalized: bool) -> tuple[int, int]:
    w, h = _primary_screen()
    if normalized:
        sx = int(round(max(0.0, min(1000.0, x)) / 1000.0 * w))
        sy = int(round(max(0.0, min(1000.0, y)) / 1000.0 * h))
    else:
        sx, sy = int(x), int(y)
    return max(0, min(w - 1, sx)), max(0, min(h - 1, sy))


def click_at(
    x: float,
    y: float,
    button: str = "left",
    double: bool = False,
    normalized: bool = True,
) -> dict[str, Any]:
    """Ekranda bir noktaya fare ile tiklar.

    Koordinatlar varsayilan olarak 0-1000 NORMALIZE (x = soldan yatay, y = yukaridan
    dikey). Once look_at_screen ile ekrani gor, tiklanacak alani belirle, sonra buraya
    tikla; ardindan type_text ile (app olmadan) yaz.
    """
    if not _IS_WIN:
        return {"error": "Fare kontrolu yalnizca Windows'ta desteklenir."}
    button = (button or "left").lower()
    pairs = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }
    if button not in pairs:
        return {"error": f"Gecersiz dugme: {button}"}
    down, up = pairs[button]
    sx, sy = _resolve_point(x, y, normalized)
    try:
        _user32.SetCursorPos(sx, sy)
        time.sleep(0.06)
        _send(_mouse_event(down))
        time.sleep(0.03)
        _send(_mouse_event(up))
        if double:
            time.sleep(0.09)
            _send(_mouse_event(down))
            time.sleep(0.03)
            _send(_mouse_event(up))
    except OSError as exc:
        return {"error": f"Tiklama basarisiz: {exc}"}
    return {"status": "tiklandi", "screen_x": sx, "screen_y": sy, "button": button, "double": double}


def _multi_click(sx: int, sy: int, times: int, button_down: int, button_up: int) -> None:
    _user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    for _ in range(max(1, times)):
        _send(_mouse_event(button_down))
        time.sleep(0.02)
        _send(_mouse_event(button_up))
        time.sleep(0.05)


def drag_select(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    normalized: bool = True,
) -> dict[str, Any]:
    """Iki nokta arasindaki metni fare ile surukleyerek secer (silmek/degistirmek icin).

    Koordinatlar 0-1000 normalize. Secimden sonra press_keys('delete') ile sil.
    """
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    sx1, sy1 = _resolve_point(start_x, start_y, normalized)
    sx2, sy2 = _resolve_point(end_x, end_y, normalized)
    try:
        _user32.SetCursorPos(sx1, sy1)
        time.sleep(0.08)
        _send(_mouse_event(MOUSEEVENTF_LEFTDOWN))
        time.sleep(0.06)
        steps = 10
        for i in range(1, steps + 1):
            ix = int(round(sx1 + (sx2 - sx1) * i / steps))
            iy = int(round(sy1 + (sy2 - sy1) * i / steps))
            _user32.SetCursorPos(ix, iy)
            time.sleep(0.02)
        time.sleep(0.06)
        _send(_mouse_event(MOUSEEVENTF_LEFTUP))
    except OSError as exc:
        return {"error": f"Secim basarisiz: {exc}"}
    return {"status": "secildi", "from": [sx1, sy1], "to": [sx2, sy2]}


def select_word(x: float, y: float, normalized: bool = True) -> dict[str, Any]:
    """Bir noktadaki kelimeyi cift tiklayarak secer."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    sx, sy = _resolve_point(x, y, normalized)
    try:
        _multi_click(sx, sy, 2, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "kelime secildi", "screen_x": sx, "screen_y": sy}


def select_line(x: float, y: float, normalized: bool = True) -> dict[str, Any]:
    """Bir noktadaki satiri/paragrafi uc tiklayarak secer."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    sx, sy = _resolve_point(x, y, normalized)
    try:
        _multi_click(sx, sy, 3, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "satir secildi", "screen_x": sx, "screen_y": sy}


def clear_field(x: float, y: float, normalized: bool = True) -> dict[str, Any]:
    """Verilen noktadaki giris alanini tumuyle temizler (tikla -> Ctrl+A -> Delete)."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    result = click_at(x, y, normalized=normalized)
    if "error" in result:
        return result
    time.sleep(0.12)
    _combo(VK_CONTROL, VK_A)
    time.sleep(0.05)
    _tap(0x2E)  # VK_DELETE
    return {"status": "alan temizlendi", "screen_x": result["screen_x"], "screen_y": result["screen_y"]}


def erase_chars(count: int, forward: bool = False) -> dict[str, Any]:
    """Imlecin bulundugu yerden `count` karakter siler (forward=False => geriye, Backspace)."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    vk = 0x2E if forward else VK_BACK
    try:
        for _ in range(max(0, int(count))):
            _tap(vk)
            time.sleep(0.01)
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "silindi", "count": int(count), "yon": "ileri" if forward else "geri"}


def move_mouse(x: float, y: float, normalized: bool = True) -> dict[str, Any]:
    """Fare imlecini bir noktaya tasir (tiklamadan)."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    sx, sy = _resolve_point(x, y, normalized)
    try:
        _user32.SetCursorPos(sx, sy)
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "tasindi", "screen_x": sx, "screen_y": sy}


def scroll(amount: int) -> dict[str, Any]:
    """Fare tekerini kaydirir. Pozitif = yukari, negatif = asagi (adim sayisi)."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    try:
        _send(_mouse_event(MOUSEEVENTF_WHEEL, data=int(amount) * WHEEL_DELTA))
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "kaydirildi", "amount": int(amount)}


def press_keys(keys: str, hwnd: int = 0) -> dict[str, Any]:
    """Klavye kisayolu / ozel tus gonderir. Orn: 'ctrl+s', 'enter', 'tab', 'ctrl+shift+n'.

    `hwnd` verilirse tuslar ONCE o pencere on plana getirilerek gonderilir; pencere on
    plana gelmezse hicbir sey gonderilmez (tuslar baska pencereye gitmesin).
    """
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    if hwnd and not focus_window(hwnd):
        return {"error": "Hedef pencere on plana getirilemedi; tus gonderilmedi."}
    parts = [p.strip().lower() for p in (keys or "").replace(" ", "").split("+") if p.strip()]
    if not parts:
        return {"error": "Tus dizisi bos."}
    vks: list[int] = []
    for part in parts:
        if part in _KEY_NAMES:
            vks.append(_KEY_NAMES[part])
        elif len(part) == 1:
            vks.append(ord(part.upper()))
        else:
            return {"error": f"Bilinmeyen tus: {part}"}
    mods, main = vks[:-1], vks[-1]
    try:
        for m in mods:
            _send(_key_event(m))
            time.sleep(0.02)
        _send(_key_event(main))
        time.sleep(0.03)
        _send(_key_event(main, up=True))
        for m in reversed(mods):
            _send(_key_event(m, up=True))
    except OSError as exc:
        return {"error": f"Tus gonderilemedi: {exc}"}
    return {"status": "gonderildi", "keys": keys}


def media_control(action: str) -> dict[str, Any]:
    """Medya/ses kontrolu: play_pause | next | prev | stop | volume_up | volume_down | mute."""
    if not _IS_WIN:
        return {"error": "yalnizca Windows"}
    a = (action or "").strip().lower().replace("-", "_")
    keymap = {
        "play_pause": VK_MEDIA_PLAY_PAUSE, "play": VK_MEDIA_PLAY_PAUSE, "pause": VK_MEDIA_PLAY_PAUSE,
        "next": VK_MEDIA_NEXT, "prev": VK_MEDIA_PREV, "previous": VK_MEDIA_PREV,
        "stop": VK_MEDIA_STOP, "mute": VK_VOLUME_MUTE,
        "volume_up": VK_VOLUME_UP, "ses_ac": VK_VOLUME_UP, "louder": VK_VOLUME_UP,
        "volume_down": VK_VOLUME_DOWN, "ses_kis": VK_VOLUME_DOWN, "quieter": VK_VOLUME_DOWN,
    }
    vk = keymap.get(a)
    if vk is None:
        return {"error": f"bilinmeyen eylem: {action}"}
    try:
        repeat = 4 if a in ("volume_up", "volume_down", "ses_ac", "ses_kis", "louder", "quieter") else 1
        for _ in range(repeat):
            _tap(vk)
            time.sleep(0.02)
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "gonderildi", "action": a}


def window_action(action: str) -> dict[str, Any]:
    """Pencere yonetimi: snap_left | snap_right | maximize | minimize | minimize_all | restore_all | switch."""
    if not _IS_WIN:
        return {"error": "yalnizca Windows"}
    a = (action or "").strip().lower().replace("-", "_")
    try:
        if a in ("snap_left", "sola", "sola_yasla"):
            _combo(VK_LWIN, VK_LEFT)
        elif a in ("snap_right", "saga", "saga_yasla"):
            _combo(VK_LWIN, VK_RIGHT)
        elif a in ("maximize", "buyut", "tam_ekran"):
            _combo(VK_LWIN, VK_UP)
        elif a in ("minimize", "kucult"):
            _combo(VK_LWIN, VK_DOWN)
        elif a in ("minimize_all", "hepsini_kucult", "masaustu"):
            _combo(VK_LWIN, VK_D)
        elif a in ("restore_all", "geri_getir"):
            _combo(VK_LWIN, VK_D)
        elif a in ("switch", "gecis", "alt_tab"):
            _send(_key_event(VK_MENU))
            time.sleep(0.05)
            _tap(VK_TAB)
            time.sleep(0.3)
            _send(_key_event(VK_MENU, up=True))
        else:
            return {"error": f"bilinmeyen eylem: {action}"}
    except OSError as exc:
        return {"error": str(exc)}
    return {"status": "gonderildi", "action": a}


def get_foreground_window() -> int:
    """O anki on plandaki pencere tanitcisini (HWND) dondurur; yoksa 0."""
    if not _IS_WIN:
        return 0
    hwnd = _user32.GetForegroundWindow()
    return int(hwnd) if hwnd else 0


def _pid_exe_path(pid: int) -> str:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def _pid_exe_name(pid: int) -> str:
    return Path(_pid_exe_path(pid)).name.lower()


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def describe_window(hwnd: int = 0) -> dict[str, Any]:
    """Bir pencerenin kimligi: {hwnd, title, exe, exe_path}. `hwnd` 0 ise on plandaki
    pencere. Pencere yoksa bos sozluk."""
    if not _IS_WIN:
        return {}
    hwnd = int(hwnd or _user32.GetForegroundWindow() or 0)
    if not hwnd or not _user32.IsWindow(wintypes.HWND(hwnd)):
        return {}
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    path = _pid_exe_path(pid.value)
    return {
        "hwnd": int(hwnd),
        "title": _window_title(hwnd),
        "exe": Path(path).name.lower(),
        "exe_path": path,
    }


def find_close_target(name: str, exe_hint: str = "") -> dict[str, Any]:
    """Adiyla kapatilacak pencereyi bulur: `describe_window` + `siblings` (ayni exe'nin
    diger gorunur pencerelerinin basliklari). Bulunamazsa bos sozluk."""
    target = describe_window(find_window(name, exe_hint)) if _IS_WIN else {}
    if not target:
        return {}
    target["siblings"] = [
        title for hwnd, (title, exe, _pid) in snapshot_windows().items()
        if exe == target["exe"] and hwnd != target["hwnd"]
    ]
    return target


def close_window(hwnd: int) -> dict[str, Any]:
    """YALNIZ verilen pencereyi nazikce kapatir (WM_CLOSE; kaydetme sorusu cikabilir)."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    if not hwnd or not _user32.IsWindow(wintypes.HWND(hwnd)):
        return {"error": "Pencere artik yok."}
    if not _user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0):
        return {"error": "Kapatma istegi gonderilemedi (erisim engellenmis olabilir)."}
    return {"status": "kapatma istegi gonderildi"}


# Odaktaki pencereyi/sekmeyi kapatan kisayollar: onaysiz gonderilmez (bkz. ToolRunner).
_CLOSE_COMBOS: set[frozenset[str]] = {
    frozenset(("alt", "f4")),
    frozenset(("ctrl", "w")),
    frozenset(("ctrl", "shift", "w")),
    frozenset(("ctrl", "f4")),
    frozenset(("ctrl", "q")),
}
_MOD_ALIASES = {"control": "ctrl", "strg": "ctrl", "menu": "alt"}


def is_close_combo(keys: str) -> bool:
    """'alt+f4', 'Ctrl + W' gibi pencere/sekme kapatan bir kisayol mu?"""
    parts = [p.strip().lower() for p in (keys or "").replace(" ", "").split("+") if p.strip()]
    return frozenset(_MOD_ALIASES.get(p, p) for p in parts) in _CLOSE_COMBOS


def find_window(name: str, exe_hint: str = "") -> int:
    """Adiyla gorunur bir ust-duzey pencere bulur (exe adi > baslik eslesmesi)."""
    if not _IS_WIN or not name:
        return 0
    needle = " ".join(name.strip().lower().split())
    exe_hint = exe_hint.strip().lower()
    matches: list[tuple[int, int]] = []

    def _cb(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd).lower()
        if not title:
            return True
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _pid_exe_name(pid.value)
        score = 0
        if exe_hint and exe == exe_hint:
            score = 4
        elif exe_hint and exe_hint.removesuffix(".exe") in exe:
            score = 3
        elif needle in title:
            score = 2
        elif needle.replace(" ", "") in exe.replace(".exe", ""):
            score = 1
        if score:
            matches.append((score, int(hwnd)))
        return True

    _user32.EnumWindows(_ENUMPROC(_cb), 0)
    if not matches:
        return 0
    matches.sort(reverse=True)
    return matches[0][1]


def focus_window(hwnd: int) -> bool:
    """Verilen pencereyi on plana getirir ve GERCEKTEN geldigini dogrular (3 deneme).

    On plan kilidini gevsetmek icin ALT yerine atanmamis F24 tusuna dokunulur:
    tek basina ALT, Not Defteri/Office gibi uygulamalarda menu cubugunu etkinlestirip
    sonraki karakterlerin menuye gitmesine yol aciyordu.
    """
    if not _IS_WIN or not hwnd:
        return False
    target = wintypes.HWND(hwnd)
    for _attempt in range(3):
        fg = _user32.GetForegroundWindow()
        if fg and int(fg) == int(hwnd):
            return True
        src = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
        dst = _user32.GetWindowThreadProcessId(target, None)

        try:
            _send(_key_event(VK_F24), _key_event(VK_F24, up=True))
        except OSError:
            pass

        attached = False
        if src and dst and src != dst:
            attached = bool(_user32.AttachThreadInput(src, dst, True))
        try:
            if _user32.IsIconic(target):
                _user32.ShowWindow(target, SW_RESTORE)
            _user32.BringWindowToTop(target)
            _user32.SetForegroundWindow(target)
        finally:
            if attached:
                _user32.AttachThreadInput(src, dst, False)
        time.sleep(0.2)
        if int(_user32.GetForegroundWindow() or 0) == int(hwnd):
            return True
    return False


def snapshot_windows() -> dict[int, tuple[str, str, int]]:
    """Gorunur, basligi olan ust-duzey pencereler: {hwnd: (baslik, exe, pid)}."""
    out: dict[int, tuple[str, str, int]] = {}
    if not _IS_WIN:
        return out

    def _cb(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out[int(hwnd)] = (title, _pid_exe_name(pid.value), int(pid.value))
        return True

    _user32.EnumWindows(_ENUMPROC(_cb), 0)
    return out


def foreground_exe() -> str:
    """On plandaki pencerenin exe adi (kucuk harf) ya da ''."""
    return _foreground_exe() if _IS_WIN else ""


def _click_into_client(hwnd: int, rel_x: float = 0.5, rel_y: float = 0.4) -> tuple[int, int]:
    """Pencerenin istemci alanina (arac cubugunun altina) tiklayarak imleci metne koyar."""
    rect = wintypes.RECT()
    _user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    w = max(1, rect.right - rect.left)
    h = max(1, rect.bottom - rect.top)
    pt = wintypes.POINT(int(w * rel_x), int(h * rel_y))
    _user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt))
    _user32.SetCursorPos(pt.x, pt.y)
    time.sleep(0.06)
    _send(_mouse_event(MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.03)
    _send(_mouse_event(MOUSEEVENTF_LEFTUP))
    return pt.x, pt.y


def type_text(
    text: str,
    app: str | None = None,
    submit: bool = False,
    per_char: float = 0.04,
    exe_hint: str = "",
    x: float | None = None,
    y: float | None = None,
) -> dict[str, Any]:
    """Metni HARF HARF yazar.

    - x,y (0-1000 normalize) verilirse: once oraya tiklar, sonra yazar (EN GUVENILIR yol).
    - app verilirse: o pencereyi bulur, one getirir ve metin alanina tiklayip yazar
      (Not Defteri gibi tek-alanli uygulamalar icin). Pencere on plana GELMEZSE yazilmaz.
    - hicbiri yoksa: o an odakta olan yere yazar.
    Yazarken odak baska pencereye kayarsa yazma durur ve `typed_chars` bildirilir.
    """
    text = text or ""
    if not _IS_WIN:
        return {"error": "Yazma yalnizca Windows'ta desteklenir."}
    if not text and not submit:
        return {"error": "Yazilacak metin bos."}

    target = "odaktaki pencere"
    guard = 0
    try:
        _release_modifiers()
        if x is not None and y is not None:
            spot = click_at(float(x), float(y), normalized=True)
            if "error" in spot:
                return spot
            target = f"ekran ({spot['screen_x']},{spot['screen_y']})"
            time.sleep(0.2)
            guard = get_foreground_window()
        elif app:
            hwnd = find_window(app, exe_hint=exe_hint)
            if not hwnd:
                return {
                    "error": f"'{app}' penceresi bulunamadi. Once open_application ile "
                    "acin, birkac saniye bekleyin, sonra tekrar deneyin."
                }
            if not focus_window(hwnd):
                return {
                    "error": f"'{app}' penceresi on plana getirilemedi (yonetici yetkili olabilir "
                    "ya da baska bir pencere odagi tutuyor). Yanlis yere yazmamak icin durdum."
                }
            time.sleep(0.18)
            cx, cy = _click_into_client(hwnd)
            time.sleep(0.18)
            if not _ensure_foreground(hwnd):
                return {"error": f"'{app}' tiklamadan sonra odagi kaybetti; yazilmadi."}
            guard = hwnd
            target = f"{_window_title(hwnd) or app} metin alani ({cx},{cy})"
        else:
            time.sleep(0.15)
            guard = get_foreground_window()

        typed = _type_text(text, per_char, guard_hwnd=guard)
        if submit:
            time.sleep(0.1)
            _tap(VK_RETURN)
    except FocusLost as exc:
        return {
            "error": "Yazarken odak baska pencereye gecti; yazma durduruldu.",
            "typed_chars": exc.typed,
            "characters": len(text),
        }
    except OSError as exc:
        return {"error": f"Klavye simulasyonu basarisiz: {exc}"}
    return {"status": "yazildi", "target": target, "characters": typed, "submitted": submit}


def close_active_tab(restore_hwnd: int = 0) -> dict[str, Any]:
    """Odaktaki tarayici/pencere sekmesini kapatir (Ctrl+W).

    `restore_hwnd` verilirse (onay diyalogu odagi calmis olabilir) once o pencere
    on plana getirilir.
    """
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    try:
        if restore_hwnd:
            _user32.SetForegroundWindow(wintypes.HWND(restore_hwnd))
            time.sleep(0.25)
        _combo(VK_CONTROL, VK_W)
        return {"status": "aktif sekme kapatildi"}
    except OSError as exc:
        return {"error": str(exc)}


def close_search() -> dict[str, Any]:
    """Acik arama/baslat panelini kapatir (Esc)."""
    if not _IS_WIN:
        return {"error": "Yalnizca Windows."}
    try:
        _tap(VK_ESCAPE)
        return {"status": "kapatildi"}
    except OSError as exc:
        return {"error": str(exc)}


# --- tum girdi fonksiyonlarini tek kilitle sirala (thread'ler arasi karisma yok) -----
def _serialized(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _INPUT_LOCK:
            return fn(*args, **kwargs)

    return wrapper


for _name in (
    "search_and_open", "type_in_search", "type_in_browser", "click_at", "drag_select",
    "select_word", "select_line", "clear_field", "erase_chars", "move_mouse", "scroll",
    "press_keys", "media_control", "window_action", "focus_window", "type_text",
    "close_active_tab", "close_search",
):
    globals()[_name] = _serialized(globals()[_name])
