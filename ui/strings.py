"""Arayuzde gorunen metinler (dogru Turkce karakterlerle) ve Turkce buyuk/kucuk harf yardimcilari.

Ajan/departman VERISI (agents/) ASCII Turkce tanimli kalir (LLM istemlerinde kullaniliyor);
arayuz gosterimi bu modul uzerinden yapilir.
"""

from __future__ import annotations


def tr_lower(text: str) -> str:
    """Turkce kucuk harf: Python lower() 'I' -> 'i' yapar (BAĞLI -> 'bağli' hatasi)."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def tr_upper(text: str) -> str:
    """Turkce buyuk harf: 'i' -> 'İ', 'ı' -> 'I'."""
    return text.replace("i", "İ").replace("ı", "I").upper()


DEPARTMENT_TITLES = {
    "okul": "Okul",
    "iletisim": "İletişim",
    "sistem": "Sistem",
    "telefon": "Telefon",
    "bilgi": "Bilgi",
    "gunluk": "Günlük & Medya",
}

TASK_STATUS_LABELS = {
    "idle": "hazır",
    "queued": "kuyrukta",
    "routing": "yönlendiriliyor",
    "running": "çalışıyor",
    "tool": "araç",
    "awaiting_approval": "onay bekliyor",
    "done": "tamam",
    "failed": "hata",
    "blocked": "kilitli",
    "cancelled": "iptal",
}

AUTONOMY_LABELS = {
    "fully_autonomous": "TAM OTONOM",
    "human_assisted": "İNSAN ONAYLI",
    "human_led": "İNSAN ODAKLI",
}
