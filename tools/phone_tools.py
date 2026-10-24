"""Telefon uygulamasi araclari: JARVIS telefonda arama, SMS, alarm, uygulama acma, konum.

Hepsi `web/phone_link.py::PHONE` kanalindan telefona gider ve telefonun yanitini bekler.
Telefon bagli degilse ya da reddederse arac `{"error"}` doner: model "aradim" diyemez.
Arama ve SMS telefonda her zaman onay karti ister (geri alinamaz eylem); onay telefonda.
(ADB araclari `tools/adb_tool.py` farklidir: telefonu PC'den USB/WiFi ile yonetir.)
"""

from __future__ import annotations

import re
from typing import Any

from web.phone_link import PHONE

_TIME = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")
_SMS_MAX = 1000


def _need(value: str, what: str) -> dict[str, Any] | None:
    return None if str(value or "").strip() else {"error": f"{what} bos olamaz."}


def phone_call(contact: str = "") -> dict[str, Any]:
    """Kisi adi ya da numarayi arar (telefon rehberden cozer, onay ister)."""
    return _need(contact, "Aranacak kisi") or PHONE.request("call", {"contact": contact.strip()})


def send_sms(contact: str = "", text: str = "") -> dict[str, Any]:
    """Kisiye/numaraya SMS gonderir (telefonda onay karti)."""
    err = _need(contact, "Alici") or _need(text, "Mesaj")
    if err:
        return err
    return PHONE.request("sms", {"contact": contact.strip(), "text": text.strip()[:_SMS_MAX]})


def set_alarm(time: str = "", label: str = "") -> dict[str, Any]:
    """Telefonda alarm kurar. `time` 'SS:DD' (24 saat)."""
    m = _TIME.match(str(time or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return {"error": "Saat 'SS:DD' biciminde olmali (orn. 07:30)."}
    return PHONE.request("alarm", {"hour": int(m.group(1)), "minute": int(m.group(2)),
                                   "label": (label or "JARVIS").strip()[:60]})


def set_timer(minutes: float = 0, label: str = "") -> dict[str, Any]:
    """Telefonda geri sayim baslatir."""
    try:
        seconds = int(round(float(minutes) * 60))
    except (TypeError, ValueError):
        seconds = 0
    if not 1 <= seconds <= 24 * 3600:
        return {"error": "Sure 1 sn ile 24 saat arasinda olmali."}
    return PHONE.request("timer", {"seconds": seconds, "label": (label or "JARVIS").strip()[:60]})


def open_phone_app(app: str = "") -> dict[str, Any]:
    """Telefonda bir uygulamayi adiyla acar (orn. 'WhatsApp', 'Instagram', 'kamera')."""
    return _need(app, "Uygulama adi") or PHONE.request("open_app", {"app": app.strip()})


def phone_location() -> dict[str, Any]:
    """Telefonun GPS konumu: {lat, lon, accuracy}."""
    return PHONE.request("location", {}, timeout=15.0)


def current_location() -> tuple[float, float] | None:
    """Rota araci icin: telefon konumu (lat, lon) ya da None."""
    reply = phone_location()
    loc = reply.get("result") if isinstance(reply, dict) else None
    try:
        return float(loc["lat"]), float(loc["lon"])
    except (TypeError, KeyError, ValueError):
        return None


def phone_status() -> dict[str, Any]:
    """Pil, sarj, ag bilgisi."""
    return PHONE.request("status", {}, timeout=10.0)


def ring_phone() -> dict[str, Any]:
    """'Telefonumu bul': sessizde olsa da telefon calar."""
    return PHONE.request("ring", {}, timeout=10.0)


def send_file_to_phone(path: str = "") -> dict[str, Any]:
    """PC'deki dosyayi telefona gonderir (telefonda bildirim, dokununca iner)."""
    from web.event_bus import BUS
    from web.phone_files import offer

    if err := _need(path, "Dosya yolu"):
        return err
    info = offer(path)
    if "error" in info:
        return info
    BUS.push("file", info)
    if PHONE.connected:
        return {"status": "telefona gonderildi", **info}
    return {"status": "hazirlandi; telefon uygulamasi baglaninca Dosyalar'da gorunecek", **info}
