"""Telegram Bot API araclari - sesli JARVIS, ILETISIM ajanlari ve otomatik yanit kolu.

TELEGRAM_BOT_TOKEN + TELEGRAM_DEFAULT_CHAT_ID (.env). Yapilandirilmamissa her arac
{"error": ...} doner - asla coker.

Gelen mesajlar `data/telegram_state.json`'da (offset + son 50 mesaj) tutulur. Telegram
ayni anda tek bir getUpdates istemcisine izin verir (409): otomatik yanit kolu
(core/telegram_handler.py) calisiyorsa `get_latest_telegram_updates` API'yi yoklamaz,
kolun yazdigi tampondan okur.

GUVENLIK: token URL'de oldugu icin URL / istisna metni ASLA loglanmaz.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from config.settings import get_settings
from core.bridge_mirror import mirror_to_bridge

API_URL = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4000          # Telegram siniri 4096
RECENT_KEEP = 50
LISTENER_STALE_S = 90.0  # kol bu kadar sn sessizse "calismiyor" sayilir

_STATE_LOCK = threading.Lock()


# ------------------------------------------------------------------ yapilandirma
def _token() -> str:
    return get_settings().telegram_bot_token


def default_chat_id() -> str:
    return get_settings().telegram_default_chat_id


def telegram_enabled() -> bool:
    return bool(_token())


def _not_configured() -> dict[str, Any]:
    return {"error": "Telegram yapilandirilmamis: .env'e TELEGRAM_BOT_TOKEN (ve "
                     "TELEGRAM_DEFAULT_CHAT_ID) ekleyin."}


def api_url(method: str, token: str | None = None) -> str:
    return API_URL.format(token=token or _token(), method=method)


def call_api(method: str, payload: dict[str, Any], *, timeout: float = 15.0) -> dict[str, Any]:
    """Senkron Bot API cagrisi; {"ok": bool, "result"|"error": ...} doner."""
    if not telegram_enabled():
        return {"ok": False, **_not_configured()}
    try:
        resp = httpx.post(api_url(method), json=payload, timeout=timeout)
        data = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"Telegram {method} basarisiz: {type(exc).__name__}")
        return {"ok": False, "error": f"Telegram'a ulasilamadi ({type(exc).__name__})"}
    if not data.get("ok"):
        desc = str(data.get("description") or f"HTTP {resp.status_code}")
        logger.warning(f"Telegram {method} reddedildi: {desc[:120]}")
        return {"ok": False, "error": desc[:200]}
    return data


# ------------------------------------------------------------------ durum / tampon
def _state_path() -> Path:
    return get_settings().data_dir / "telegram_state.json"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"offset": 0, "recent": [], "heartbeat": 0.0}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug(f"telegram durumu yazilamadi: {exc!r}")


def touch_heartbeat() -> None:
    with _STATE_LOCK:
        state = load_state()
        state["heartbeat"] = time.time()
        _save_state(state)


def listener_active() -> bool:
    return time.time() - float(load_state().get("heartbeat") or 0) < LISTENER_STALE_S


def normalize_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """getUpdates ogesini sade bir mesaj sozlugune cevirir (metinsiz ogeler None)."""
    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return None
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    text = msg.get("text") or msg.get("caption") or ""
    if not text:
        return None
    name = " ".join(
        p for p in (sender.get("first_name"), sender.get("last_name")) if p
    ) or sender.get("username") or chat.get("title") or str(chat.get("id"))
    return {
        "update_id": update.get("update_id"),
        "chat_id": str(chat.get("id", "")),
        "chat_type": chat.get("type", ""),
        "chat_title": chat.get("title") or name,
        "sender": name,
        "message_id": msg.get("message_id"),
        "text": text,
        "date": msg.get("date"),
    }


def record_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Offset'i ilerletir, metin mesajlarini tampona ekler ve yeni mesajlari doner."""
    if not updates:
        return []
    fresh: list[dict[str, Any]] = []
    with _STATE_LOCK:
        state = load_state()
        offset = int(state.get("offset") or 0)
        for upd in updates:
            offset = max(offset, int(upd.get("update_id") or 0) + 1)
            item = normalize_update(upd)
            if item:
                fresh.append(item)
        state["offset"] = offset
        state["recent"] = (list(state.get("recent") or []) + fresh)[-RECENT_KEEP:]
        _save_state(state)
    return fresh


def _chat_label(chat_id: str) -> str:
    for item in reversed(load_state().get("recent") or []):
        if item.get("chat_id") == chat_id:
            return str(item.get("chat_title") or chat_id)
    return chat_id


# ------------------------------------------------------------------ araclar
def send_telegram_message(text: str, chat_id: str = "", mirror: bool = True) -> dict[str, Any]:
    """Telegram'dan mesaj gonderir. chat_id bos ise varsayilan sohbete (TELEGRAM_DEFAULT_CHAT_ID)."""
    if not telegram_enabled():
        return _not_configured()
    text = (text or "").strip()
    chat_id = str(chat_id or default_chat_id()).strip()
    if not text:
        return {"error": "'text' bos olamaz."}
    if not chat_id:
        return {"error": "chat_id yok ve TELEGRAM_DEFAULT_CHAT_ID tanimli degil."}
    data = call_api("sendMessage", {"chat_id": chat_id, "text": text[:MAX_TEXT]})
    if not data.get("ok"):
        return {"error": data.get("error", "gonderilemedi")}
    if mirror:
        mirror_to_bridge(f"[TELEGRAM] (JARVIS->{_chat_label(chat_id)}): {text[:200]}")
    return {"status": "gonderildi", "chat_id": chat_id,
            "message_id": (data.get("result") or {}).get("message_id")}


def reply_to_telegram_message(
    chat_id: str, message_id: int, text: str, mirror: bool = True
) -> dict[str, Any]:
    """Belirli bir Telegram mesajina alinti-yanit verir (chat_id + message_id get_latest_telegram_updates'ten)."""
    if not telegram_enabled():
        return _not_configured()
    text = (text or "").strip()
    if not text or not str(chat_id).strip():
        return {"error": "'chat_id' ve 'text' zorunlu."}
    payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text[:MAX_TEXT]}
    try:
        payload["reply_parameters"] = {"message_id": int(message_id),
                                       "allow_sending_without_reply": True}
    except (TypeError, ValueError):
        pass
    data = call_api("sendMessage", payload)
    if not data.get("ok"):
        return {"error": data.get("error", "gonderilemedi")}
    if mirror:
        mirror_to_bridge(f"[TELEGRAM] (JARVIS->{_chat_label(str(chat_id))}): {text[:200]}")
    return {"status": "yanitlandi", "chat_id": str(chat_id),
            "message_id": (data.get("result") or {}).get("message_id")}


def get_latest_telegram_updates(limit: int = 10) -> dict[str, Any]:
    """Telegram'a gelen son mesajlari listeler (gonderen, sohbet, metin, chat_id, message_id)."""
    if not telegram_enabled():
        return _not_configured()
    limit = max(1, min(int(limit or 10), RECENT_KEEP))
    if not listener_active():
        # otomatik yanit kolu calismiyor -> API'yi kendimiz yoklariz (bekletmeden)
        offset = int(load_state().get("offset") or 0)
        data = call_api("getUpdates", {"offset": offset, "timeout": 0,
                                       "allowed_updates": ["message", "edited_message"]})
        if not data.get("ok"):
            return {"error": data.get("error", "guncellemeler alinamadi")}
        record_updates(list(data.get("result") or []))
    recent = list(load_state().get("recent") or [])[-limit:]
    return {"count": len(recent), "messages": list(reversed(recent))}
