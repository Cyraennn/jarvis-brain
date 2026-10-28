"""Canli beynin kisilik modlari: JARVIS / FRIDAY / ULTRON.

Uc mod da ayni Gemini Live oturumunu kullanir; degisen yalnizca sistem promptunun
kimlik bolumu (prompts/personas/<key>.md), Gemini hazir sesi ve istege bagli ses
efektidir. Secim data/persona.json'a yazilir, yeniden baslatmada korunur.

Not: agents/stark_team.py'deki PERSONAS, /ekip web sayfasinin metin personalaridir;
bu modul ondan bagimsizdir.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_KEY = "jarvis"
# Ad degisikligi oncesi kayitli anahtarlar (data/persona.json, eski istemciler)
_LEGACY_KEYS = {"cyraen": "jarvis"}
_STATE_FILE = "persona.json"


@dataclass(frozen=True)
class PersonaMode:
    key: str
    name: str
    color: str
    voice_name: str
    audio_effect: str = ""  # "" = efektsiz, "ultron" = core.voice_fx.UltronFx


# (anahtar, ad, renk) - HUD'daki cip sirasi
CHIPS: tuple[tuple[str, str, str], ...] = (
    ("jarvis", "JARVIS", "#3da9fc"),
    ("friday", "FRIDAY", "#2ee59d"),
    ("ultron", "ULTRON", "#ff3b3b"),
)


def modes(settings: Any) -> dict[str, PersonaMode]:
    voices = {
        "jarvis": getattr(settings, "voice_name", "Puck"),
        "friday": getattr(settings, "friday_voice", "Kore"),
        "ultron": getattr(settings, "ultron_voice", "Charon"),
    }
    fx = {"ultron": "ultron" if getattr(settings, "ultron_fx", True) else ""}
    return {
        key: PersonaMode(key, name, color, voices[key], fx.get(key, ""))
        for key, name, color in CHIPS
    }


def get(settings: Any, key: str | None) -> PersonaMode:
    table = modes(settings)
    k = (key or "").strip().lower()
    return table.get(_LEGACY_KEYS.get(k, k), table[DEFAULT_KEY])


def _state_path(settings: Any) -> Path:
    return Path(settings.data_dir) / _STATE_FILE


def load_active(settings: Any) -> PersonaMode:
    try:
        data = json.loads(_state_path(settings).read_text(encoding="utf-8"))
        key = data.get("persona") if isinstance(data, dict) else None
    except (OSError, ValueError):
        key = None
    return get(settings, key)


def save_active(settings: Any, key: str) -> None:
    path = _state_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"persona": key}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning(f"Kisilik secimi kaydedilemedi: {exc!r}")
