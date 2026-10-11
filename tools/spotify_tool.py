"""Spotify Web API (OAuth) araclari - ara-cal, duraklat/gec, kuyruk, ses, cihaz, "ne caliyor".

Oynatma kontrolu Spotify Premium ister. Kurulum (bir kez):
  1. developer.spotify.com/dashboard -> Create app -> Redirect URI:
     http://127.0.0.1:8888/callback ("Web API" isaretli).
  2. .env: SPOTIFY_CLIENT_ID=... , SPOTIFY_CLIENT_SECRET=...
  3. `python scripts/spotify_auth.py` -> tarayicida izin ver -> data/spotify_token.json olusur.

Token yoksa `spotify_enabled()` False doner. Tum fonksiyonlar senkron ve hata durumunda
{"error": ...} doner - asla coker. Aktif cihaz yoksa Spotify masaustu uygulamasi
acilir ve cihaz gorunene kadar beklenir (zamanli "sabah X cal" gorevleri icin).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import get_settings

SCOPES = ("user-read-playback-state user-modify-playback-state "
          "user-read-currently-playing playlist-read-private")

_LOCK = threading.Lock()
_CLIENT: Any = None

_KINDS = {"track": "tracks", "artist": "artists", "album": "albums", "playlist": "playlists"}
_DEVICE_WAIT_S = 15.0


# ------------------------------------------------------------------ kimlik / istemci
def _token_path() -> Path:
    return Path(get_settings().spotify_token_file)


def spotify_enabled() -> bool:
    """client id/secret + yetkilendirilmis token var mi (etkilesimli giris gerekmeden)."""
    s = get_settings()
    return bool(s.spotify_client_id and s.spotify_client_secret) and _token_path().is_file()


def _auth_manager(open_browser: bool = False) -> Any:
    from spotipy.cache_handler import CacheFileHandler
    from spotipy.oauth2 import SpotifyOAuth

    s = get_settings()
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return SpotifyOAuth(
        client_id=s.spotify_client_id,
        client_secret=s.spotify_client_secret,
        redirect_uri=s.spotify_redirect_uri,
        scope=SCOPES,
        cache_handler=CacheFileHandler(cache_path=str(path)),
        open_browser=open_browser,
    )


def authorize_interactive() -> Path:
    """Tarayicida OAuth izni alir ve token'i yazar (scripts/spotify_auth.py kullanir)."""
    s = get_settings()
    if not (s.spotify_client_id and s.spotify_client_secret):
        raise RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET .env'de yok.")
    am = _auth_manager(open_browser=True)
    am.get_access_token(as_dict=False)
    _reset_client()
    return _token_path()


def _reset_client() -> None:
    global _CLIENT
    with _LOCK:
        _CLIENT = None


def _client() -> Any:
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            import spotipy

            _CLIENT = spotipy.Spotify(auth_manager=_auth_manager(), requests_timeout=10, retries=2)
        return _CLIENT


def _guard(fn_name: str, exc: BaseException) -> dict[str, Any]:
    logger.warning(f"Spotify {fn_name} hatasi: {exc!r}")
    status = getattr(exc, "http_status", None)
    msg = getattr(exc, "msg", None) or str(exc)
    reason = str(getattr(exc, "reason", "") or "")
    if status == 403 and ("premium" in (reason + str(msg)).lower()):
        return {"error": "Spotify bu islemi reddetti - oynatma kontrolu Premium hesap ister."}
    if status == 403 and "scope" in str(msg).lower():
        return {"error": "Spotify izni yetersiz - `python scripts/spotify_auth.py` ile yeniden yetki ver."}
    return {"error": f"Spotify {fn_name} basarisiz: {type(exc).__name__}: {str(msg)[:160]}"}


def _not_configured() -> dict[str, Any]:
    return {"error": "Spotify yapilandirilmamis (.env SPOTIFY_CLIENT_ID/SECRET + "
                     "`python scripts/spotify_auth.py`)."}


# ------------------------------------------------------------------ cihazlar
def _device_list(sp: Any) -> list[dict[str, Any]]:
    return (sp.devices() or {}).get("devices") or []


def _match_device(devices: list[dict[str, Any]], wanted: str) -> dict[str, Any] | None:
    w = (wanted or "").strip().lower()
    if not devices:
        return None
    if w:
        if w in ("telefon", "phone", "mobil", "smartphone"):
            hits = [d for d in devices if (d.get("type") or "").lower() == "smartphone"]
        elif w in ("pc", "bilgisayar", "computer", "masaustu"):
            hits = [d for d in devices if (d.get("type") or "").lower() == "computer"]
        else:
            hits = [d for d in devices if w in (d.get("name") or "").lower()]
        return hits[0] if hits else None
    active = [d for d in devices if d.get("is_active")]
    if active:
        return active[0]
    computers = [d for d in devices if (d.get("type") or "").lower() == "computer"]
    return (computers or devices)[0]


def _launch_desktop_app() -> bool:
    if sys.platform != "win32":
        return False
    try:
        os.startfile("spotify:")  # type: ignore[attr-defined]  # URI isleyicisi uygulamayi acar
        return True
    except OSError as exc:
        logger.warning(f"Spotify uygulamasi acilamadi: {exc!r}")
        return False


def _resolve_device(sp: Any, wanted: str = "", launch: bool = True) -> dict[str, Any] | None:
    """Istenen (ya da varsayilan/aktif) cihazi bulur; hic yoksa masaustu uygulamasini acip bekler."""
    wanted = wanted or get_settings().spotify_default_device
    dev = _match_device(_device_list(sp), wanted)
    if dev or not launch:
        return dev
    if not _launch_desktop_app():
        return None
    deadline = time.monotonic() + _DEVICE_WAIT_S
    while time.monotonic() < deadline:
        time.sleep(1.5)
        dev = _match_device(_device_list(sp), wanted)
        if dev:
            return dev
    return None


def _no_device(wanted: str = "") -> dict[str, Any]:
    tail = f" ('{wanted}' bulunamadi)" if wanted else ""
    return {"error": f"Calacak Spotify cihazi yok{tail}. Spotify'i PC'de ya da telefonda acin."}


# ------------------------------------------------------------------ yardimcilar
def _artists(item: dict[str, Any]) -> str:
    return ", ".join(a.get("name", "") for a in item.get("artists") or [])


def _search_first(sp: Any, query: str, kind: str) -> dict[str, Any] | None:
    # market="from_token" user-read-private kapsami ister; gerek yok
    res = sp.search(q=query, type=kind, limit=5)
    items = [i for i in ((res or {}).get(_KINDS[kind]) or {}).get("items") or [] if i]
    return items[0] if items else None


def _describe(item: dict[str, Any], kind: str) -> str:
    name = item.get("name", "")
    if kind in ("track", "album"):
        return f"{name} - {_artists(item)}"
    if kind == "playlist":
        return f"{name} (calma listesi)"
    return name


# ------------------------------------------------------------------ araclar
def spotify_play(query: str = "", kind: str = "track", device: str = "") -> dict[str, Any]:
    """Spotify'da muzik calar. query bossa kaldigi yerden devam eder; doluysa arar ve ilk sonucu calar.
    kind: track (sarki, varsayilan) | artist (sanatci) | album | playlist (calma listesi).
    device: bos = aktif/varsayilan cihaz; 'pc', 'telefon' ya da cihaz adi. Spotify kapaliysa PC'de acilir."""
    if not spotify_enabled():
        return _not_configured()
    kind = (kind or "track").strip().lower()
    if kind not in _KINDS:
        return {"error": f"Gecersiz kind '{kind}'. Secenekler: {', '.join(_KINDS)}"}
    try:
        sp = _client()
        dev = _resolve_device(sp, device)
        if dev is None:
            return _no_device(device)
        query = (query or "").strip()
        if not query:
            sp.start_playback(device_id=dev["id"])
            return {"ok": True, "playing": "devam", "device": dev.get("name")}
        item = _search_first(sp, query, kind)
        if item is None:
            return {"error": f"Spotify'da '{query}' icin sonuc bulunamadi."}
        album_uri = (item.get("album") or {}).get("uri")
        if kind == "track" and album_uri:
            # Windows masaustu istemcisi `uris=[...]` komutunu kabul edip calmiyor;
            # albumu sarkinin konumundan baslatmak guvenilir calisiyor.
            sp.start_playback(device_id=dev["id"], context_uri=album_uri, offset={"uri": item["uri"]})
        elif kind == "track":
            sp.start_playback(device_id=dev["id"], uris=[item["uri"]])
        else:
            sp.start_playback(device_id=dev["id"], context_uri=item["uri"])
        return {"ok": True, "playing": _describe(item, kind), "kind": kind,
                "device": dev.get("name"), "uri": item["uri"]}
    except Exception as exc:  # noqa: BLE001 - arac asla cokmez
        return _guard("play", exc)


_ACTIONS = ("pause", "resume", "next", "previous", "shuffle_on", "shuffle_off",
            "repeat_off", "repeat_track", "repeat_context")


def spotify_control(action: str) -> dict[str, Any]:
    """Spotify oynatmayi kontrol eder. action: pause (duraklat) | resume (devam) | next (sonraki) |
    previous (onceki) | shuffle_on | shuffle_off | repeat_off | repeat_track | repeat_context."""
    if not spotify_enabled():
        return _not_configured()
    action = (action or "").strip().lower()
    if action not in _ACTIONS:
        return {"error": f"Gecersiz action '{action}'. Secenekler: {', '.join(_ACTIONS)}"}
    try:
        sp = _client()
        if action == "resume":
            dev = _resolve_device(sp)
            if dev is None:
                return _no_device()
            sp.start_playback(device_id=dev["id"])
        elif action == "pause":
            sp.pause_playback()
        elif action == "next":
            sp.next_track()
        elif action == "previous":
            sp.previous_track()
        elif action.startswith("shuffle_"):
            sp.shuffle(action == "shuffle_on")
        else:
            sp.repeat(action.split("_", 1)[1])
        return {"ok": True, "action": action}
    except Exception as exc:  # noqa: BLE001
        return _guard(action, exc)


def spotify_now_playing() -> dict[str, Any]:
    """Spotify'da su an ne caldigini soyler: sarki, sanatci, cihaz, ilerleme, calip calmadigi."""
    if not spotify_enabled():
        return _not_configured()
    try:
        pb = _client().current_playback()
        if not pb or not pb.get("item"):
            return {"ok": True, "playing": False, "message": "Su an Spotify'da bir sey calmiyor."}
        item = pb["item"]
        pos, dur = (pb.get("progress_ms") or 0) // 1000, (item.get("duration_ms") or 0) // 1000
        return {
            "ok": True,
            "playing": bool(pb.get("is_playing")),
            "track": item.get("name"),
            "artist": _artists(item),
            "album": (item.get("album") or {}).get("name"),
            "device": (pb.get("device") or {}).get("name"),
            "volume": (pb.get("device") or {}).get("volume_percent"),
            "progress": f"{pos // 60}:{pos % 60:02d} / {dur // 60}:{dur % 60:02d}",
            "shuffle": pb.get("shuffle_state"),
        }
    except Exception as exc:  # noqa: BLE001
        return _guard("now_playing", exc)


def spotify_queue(query: str) -> dict[str, Any]:
    """Bir sarkiyi arayip Spotify calma kuyruguna (siradakiler) ekler."""
    if not spotify_enabled():
        return _not_configured()
    if not (query or "").strip():
        return {"error": "query zorunlu"}
    try:
        sp = _client()
        item = _search_first(sp, query.strip(), "track")
        if item is None:
            return {"error": f"Spotify'da '{query}' icin sarki bulunamadi."}
        sp.add_to_queue(item["uri"])
        return {"ok": True, "queued": _describe(item, "track")}
    except Exception as exc:  # noqa: BLE001
        return _guard("queue", exc)


def spotify_volume(percent: int) -> dict[str, Any]:
    """Spotify ses seviyesini 0-100 arasi bir yuzdeye ayarlar (aktif cihazda)."""
    if not spotify_enabled():
        return _not_configured()
    try:
        value = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        return {"error": f"Gecersiz ses seviyesi: {percent!r}"}
    try:
        sp = _client()
        dev = _resolve_device(sp, launch=False)
        if dev is None:
            return _no_device()
        sp.volume(value, device_id=dev["id"])
        return {"ok": True, "volume": value, "device": dev.get("name")}
    except Exception as exc:  # noqa: BLE001
        return _guard("volume", exc)


def spotify_devices() -> dict[str, Any]:
    """Spotify Connect cihazlarini (PC, telefon, hoparlor) ve hangisinin aktif oldugunu listeler."""
    if not spotify_enabled():
        return _not_configured()
    try:
        devices = _device_list(_client())
        return {"ok": True, "devices": [
            {"name": d.get("name"), "type": d.get("type"), "active": bool(d.get("is_active")),
             "volume": d.get("volume_percent")} for d in devices]}
    except Exception as exc:  # noqa: BLE001
        return _guard("devices", exc)
