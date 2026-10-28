"""Masaustu (Windows PC) handler'lari: mevcut arac modullerini oldugu gibi kullanir.

Sunucunun istedigi her eylem `remote/protocol.py::CLIENT_FUNCTIONS` izin listesindeki bir
"<modul>.<fonksiyon>" adidir. Burada o fonksiyon import edilip DEGISTIRILMEDEN handler
olarak kaydedilir - klavye, fare, uygulama acma, dosya, ekran, ADB mantigi yeniden yazilmaz.

Onay gerektiren islemler (surec oldurme, kod calistirma, uygulama kapatma, e-posta...)
icin onay SUNUCUDA alinir; buraya gelen istek zaten onaylanmistir.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from loguru import logger

from client.config import ClientConfig
from client.core import JarvisClient
from remote.protocol import CLIENT_FUNCTIONS


def resolve(action: str) -> Callable[..., Any] | None:
    """Izin listesindeki bir eylem adini gercek fonksiyona cevirir (listede degilse None)."""
    if action not in CLIENT_FUNCTIONS:
        return None
    module_name, _, attr = action.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - eksik bagimlilik bir eylemi kapatir, hepsini degil
        logger.warning(f"'{action}' yuklenemedi ({exc!r}) - bu eylem bu istemcide KAPALI.")
        return None
    fn = getattr(module, attr, None)
    return fn if callable(fn) else None


def register_desktop_handlers(client: JarvisClient, cfg: ClientConfig) -> list[str]:
    registered: list[str] = []
    for action in CLIENT_FUNCTIONS:
        fn = resolve(action)
        if fn is not None:
            client.register(action, fn)
            registered.append(action)

    # Jest HUD sayfasi sunucudaki web konsolunda; yerel 127.0.0.1'i degil SUNUCUYU ac
    def open_gesture_hud() -> dict[str, Any]:
        import webbrowser

        url = f"http://{cfg.server_host}:{cfg.web_port}/hud?key={cfg.web_token}"
        webbrowser.open(url)
        return {"status": "Jest HUD acildi", "url": url.split("?")[0]}

    client.register("tools.app_launcher.open_gesture_hud", open_gesture_hud)

    def open_console_app(path: str, params: dict | None = None, size: str = "1440,900") -> dict[str, Any]:
        import webbrowser
        from urllib.parse import urlencode

        if not str(path).startswith("/") or "//" in str(path):
            return {"error": "gecersiz yol"}
        query = {**(params or {}), "key": cfg.web_token}
        url = f"http://{cfg.server_host}:{cfg.web_port}{path}?{urlencode(query)}"
        webbrowser.open(url)
        return {"status": "acildi", "url": url.split("?")[0]}

    client.register("tools.app_launcher.open_console_app", open_console_app)
    logger.info(f"Masaustu eylemleri kaydedildi: {len(registered)}/{len(CLIENT_FUNCTIONS)}")
    return registered


def make_confirm_handler(mode: str) -> Callable[..., bool] | None:
    """Onay istekleri nasil gosterilsin: 'dialog' (Windows mesaj kutusu), 'console', 'deny'.

    Isleyiciler opsiyonel 3. parametre `cancel` (threading.Event) alir: karar telefondan/webden
    verilirse set edilir ve acik pencere kendiliginden kapanir (tek seferde onay).
    """
    if mode == "deny":
        return lambda prompt, source, cancel=None: False
    if mode == "console":
        def ask_console(prompt: str, source: str, cancel: Any = None) -> bool:
            answer = input(f"\n[JARVIS ONAY - {source}] {prompt}\nOnayliyor musun? (e/h): ")
            return answer.strip().lower() in ("e", "evet", "y", "yes")
        return ask_console

    def ask_dialog(prompt: str, source: str, cancel: Any = None) -> bool:
        import ctypes
        import sys
        import threading
        import uuid

        if sys.platform != "win32":
            return ask_console_fallback(prompt, source)
        MB_YESNO, MB_ICONQUESTION, MB_TOPMOST, MB_SETFOREGROUND = 0x4, 0x20, 0x40000, 0x10000
        IDYES, IDNO, WM_COMMAND = 6, 7, 0x0111
        user32 = ctypes.windll.user32
        # benzersiz baslik: uzaktan kapatirken dogru pencereyi bulmak icin
        title = f"JARVIS - Onay ({source}) #{uuid.uuid4().hex[:4]}"

        done = threading.Event()  # pencere yerelde cevaplandi -> kapatici thread biter

        if cancel is not None:
            def close_when_resolved_elsewhere() -> None:
                while not cancel.wait(0.25):
                    if done.is_set():
                        return
                # karar baska cihazda verildi: pencereyi bul ve kapat (henuz acilmamis olabilir)
                while not done.is_set():
                    hwnd = user32.FindWindowW(None, title)
                    if hwnd:
                        user32.SendMessageW(hwnd, WM_COMMAND, IDNO, 0)
                    done.wait(0.2)

            threading.Thread(target=close_when_resolved_elsewhere, daemon=True,
                             name="jarvis-confirm-closer").start()

        try:
            result = user32.MessageBoxW(
                None, prompt, title,
                MB_YESNO | MB_ICONQUESTION | MB_TOPMOST | MB_SETFOREGROUND,
            )
        finally:
            done.set()
        return result == IDYES

    def ask_console_fallback(prompt: str, source: str) -> bool:
        answer = input(f"\n[JARVIS ONAY - {source}] {prompt}\n(e/h): ")
        return answer.strip().lower() in ("e", "evet")

    return ask_dialog
