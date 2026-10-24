"""Sunucuya ozel ayarlar (.env) + mevcut `Settings`'in sunucu icin zorunlu ayarlari."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from config.settings import APP_DIR, Settings

MIN_TOKEN_LEN = 24


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


@dataclass(frozen=True)
class ServerConfig:
    token: str
    bind: str
    port: int
    command_timeout: float
    log_path: Path
    telegram_bot_token: str
    telegram_chat_id: str
    probe_models: bool

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def validate_bind(bind: str) -> str:
    """Sunucu ASLA tum arayuzlere (0.0.0.0 / ::) acilmaz: yalnizca 127.0.0.1 veya Tailscale IP'si."""
    bind = (bind or "").strip()
    if bind in ("", "0.0.0.0", "::", "[::]", "*"):
        raise SystemExit(
            f"CYRAEN_SERVER_BIND='{bind}' reddedildi: sunucu internete acilmamali. "
            "127.0.0.1 ya da Tailscale IP'nizi (tailscale ip -4) yazin."
        )
    if bind != "localhost":
        try:
            ipaddress.ip_address(bind)
        except ValueError as exc:
            raise SystemExit(f"CYRAEN_SERVER_BIND gecerli bir IP degil: {bind!r}") from exc
    return bind


def load_server_config() -> ServerConfig:
    token = os.getenv("CYRAEN_TOKEN", "").strip()
    if len(token) < MIN_TOKEN_LEN:
        raise SystemExit(
            f"CYRAEN_TOKEN .env'de tanimli degil ya da cok kisa (en az {MIN_TOKEN_LEN} karakter). "
            "Uretmek icin: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    bind = validate_bind(os.getenv("CYRAEN_SERVER_BIND", "127.0.0.1"))
    port = int(os.getenv("CYRAEN_SERVER_PORT", "8765") or 8765)
    log_path = Path(os.getenv("CYRAEN_SERVER_LOG", "") or APP_DIR / "data" / "logs" / "server.jsonl")
    return ServerConfig(
        token=token,
        bind=bind,
        port=port,
        command_timeout=_env_float("CYRAEN_COMMAND_TIMEOUT", 90.0),
        log_path=log_path,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        probe_models=_env_bool("CYRAEN_MODEL_PROBE", True),
    )


def server_settings(base: Settings, cfg: ServerConfig) -> Settings:
    """Gozetimsiz sunucu icin guvenlik ayarlarini ZORLA (kullanicinin .env'i ne derse desin).

    - ses her zaman ag uzerinden (VPS'te mikrofon yok)
    - web konsolu + ses sunucusu da ayni guvenli adrese baglanir; ayri token verilmemisse CYRAEN_TOKEN
    - geri alinamaz / riskli islemler (e-posta gonderme, surec oldurme, kod calistirma, uygulama
      kapatma) ve "Insan Onayli" ajanlar ONAYSIZ calismaz; onay gelmezse REDDEDILIR
    """
    return base.model_copy(update={
        "audio_mode": "network",
        "web_console_bind": cfg.bind,
        "web_console_token": base.web_console_token or cfg.token,
        "remote_audio_token": base.remote_audio_token or cfg.token,
        "confirm_before_close": True,
        "email_require_confirm": True,
        "agents_require_approval": True,
        "agents_auto_approve_assisted": False,
        # VPS'te Ollama yok: yerel model yedegi yalnizca acikca istenirse
        "local_llm_enabled": _env_bool("CYRAEN_LOCAL_LLM", False),
        "offline_voice_enabled": _env_bool("CYRAEN_OFFLINE_VOICE", False),
        "speaker_verify_enabled": _env_bool("CYRAEN_SPEAKER_VERIFY", False),
    })
