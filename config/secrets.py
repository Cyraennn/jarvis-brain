"""Gizli degerler (telefon PIN'i vb.) icin opsiyonel OS anahtar deposu.

`keyring` kuruluysa Windows Credential Manager kullanilir; degilse her fonksiyon
sessizce `None`/`False` doner ve cagiran taraf `.env` yedegine duser.
"""
from __future__ import annotations

_SERVICE = "jarvis-brain"


def _kr():
    try:
        import keyring  # type: ignore

        return keyring
    except Exception:  # noqa: BLE001 - kurulu degil ya da backend yok
        return None


def get_secret(name: str) -> str | None:
    kr = _kr()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE, name) or None
    except Exception:  # noqa: BLE001
        return None


def set_secret(name: str, value: str) -> bool:
    kr = _kr()
    if kr is None:
        return False
    try:
        kr.set_password(_SERVICE, name, value)
        return True
    except Exception:  # noqa: BLE001
        return False
