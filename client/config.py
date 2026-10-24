"""Istemci ayarlari: `client/.env` (sunucu adresi + token + hangi parcalar acik)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from config.legacy_env import LEGACY_PREFIX, PREFIX, alias_legacy_env

CLIENT_DIR = Path(__file__).resolve().parent
ENV_PATH = CLIENT_DIR / ".env"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


@dataclass(frozen=True)
class ClientConfig:
    server_host: str
    server_port: int
    token: str
    name: str
    kind: str
    audio: bool
    audio_port: int
    audio_token: str
    desktop: bool
    vision: bool
    confirm_mode: str          # "dialog" | "console" | "deny"
    web_port: int
    web_token: str

    @property
    def ws_url(self) -> str:
        return f"ws://{self.server_host}:{self.server_port}/ws"

    @property
    def audio_url(self) -> str:
        return f"ws://{self.server_host}:{self.audio_port}/?key={self.audio_token}"


def load_client_config(env_path: Path | None = None) -> ClientConfig:
    path = env_path or ENV_PATH
    if path.is_file():
        # client/.env ONCE yuklenir; cyraen-brain/.env'deki ayni adli degerleri ezer
        load_dotenv(path, override=True)
        # eski adli client/.env (JARVIS_*) de ana .env'i ezebilsin; yeni ad yazildiysa o kazanir
        values = dotenv_values(path)
        for key, val in values.items():
            if key.startswith(LEGACY_PREFIX) and val is not None:
                new_key = PREFIX + key[len(LEGACY_PREFIX):]
                if new_key not in values:
                    os.environ[new_key] = val
    alias_legacy_env()
    host = os.getenv("CYRAEN_SERVER_HOST", "").strip()
    token = os.getenv("CYRAEN_TOKEN", "").strip()
    if not host or not token:
        raise SystemExit(
            f"{path} icinde CYRAEN_SERVER_HOST ve CYRAEN_TOKEN dolu olmali "
            "(ornek: client/.env.example)."
        )
    return ClientConfig(
        server_host=host,
        server_port=int(os.getenv("CYRAEN_SERVER_PORT", "8765") or 8765),
        token=token,
        name=os.getenv("CYRAEN_CLIENT_NAME", "pc").strip() or "pc",
        kind=os.getenv("CYRAEN_CLIENT_KIND", "desktop").strip() or "desktop",
        audio=_bool("CYRAEN_CLIENT_AUDIO", True),
        audio_port=int(os.getenv("CYRAEN_REMOTE_AUDIO_PORT", "8771") or 8771),
        audio_token=os.getenv("CYRAEN_REMOTE_AUDIO_TOKEN", "").strip() or token,
        desktop=_bool("CYRAEN_CLIENT_DESKTOP", True),
        vision=_bool("CYRAEN_CLIENT_VISION", True),
        confirm_mode=(os.getenv("CYRAEN_CLIENT_CONFIRM", "dialog").strip().lower() or "dialog"),
        web_port=int(os.getenv("CYRAEN_WEB_PORT", "8770") or 8770),
        web_token=os.getenv("CYRAEN_WEB_TOKEN", "").strip() or token,
    )
