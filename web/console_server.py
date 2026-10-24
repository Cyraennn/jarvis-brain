"""JARVIS yerel web konsolu sunucusu (stdlib http.server).

Telefondan `http://<pc-lan-ip>:<port>?key=<token>` ile acilir.
  GET  /                 -> mobil kontrol sayfasi
  GET  /api/state        -> anlik durum (JSON)
  GET  /api/events       -> SSE canli akis
  POST /api/say          -> {"text": "..."} JARVIS canli oturumuna enjekte
  POST /api/task         -> {"task": "...", "agent": "auto"} orkestratore gorev
  POST /api/phone-event  -> {"app": "...", "text": "..."} telefon bildirim aynasi
  POST /api/control      -> {"action": "mic_on|mic_off|away_on|away_off|wake_on|wake_off"} PC ses kontrolu
  POST /api/confirm      -> {"id": "...", "approve": true|false} bekleyen onay istegini coz
  GET  /api/events?client=phone -> telefon uygulamasi (web/phone_link.py: eylem kanali acilir)
  POST /api/phone-result -> {"id", "ok", "result"|"error"} telefonun phone_action yaniti
  POST /api/files/upload?name=  -> ham govde, ~/Downloads/JARVIS'e (web/phone_files.py)
  GET  /api/files        -> telefona sunulan dosyalar; GET /api/files/get?name= indirir
  GET  /pair             -> telefon eslestirme QR'i (yalnizca localhost; jarvis://pair?host&port&key)
  GET  /api/screen/stream -> PC ekrani MJPEG; POST /api/remote/input fare/klavye (web/remote_desktop.py,
                            yalnizca JARVIS_REMOTE_DESKTOP=1 iken; aksi halde 403)
  POST /api/okul/push    -> okul (BOTE Ders Merkezi) tam durum JSON'u (localStorage aynasi)
  GET  /api/okul/pull    -> JARVIS'in okul'a ilettigi bekleyen degisiklikler (+ kuyrugu bosaltir)
  GET  /hud              -> el-jesti kontrollu 3D HUD (webcam + MediaPipe, tarayicida)
  GET  /gesture/<dosya>  -> HUD'un jest modulleri (statik JS, ui/gesture yerine web/static/gesture)
  POST /api/gesture      -> {"gesture":"select","part":"..."} -> ilgili ajana kisa aciklama sorar
  GET  /el               -> El Kontrolu + Kitaplik (web/el_page.py; ?el=demo, &kitaplik=1)
  GET  /models/<dosya>   -> yerel MediaPipe modelleri/wasm (scripts/el_modeli_indir.py)
  *    /api/el/*, /api/kitaplik/* -> web/el_api.py
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import shutil
import socket
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse

from loguru import logger

from config.settings import ASSETS_DIR
from web.confirm_registry import REGISTRY
from web.event_bus import BUS
from web import phone_files
from web.phone_link import PHONE
from web.hud_page import render_hud_page
from web.page import PWA_SERVICE_WORKER, render_manifest, render_page
from web.team_page import render_team_page

_ICON_FILES = {
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
    "/icon-maskable-512.png": "icon-maskable-512.png",
    "/apple-touch-icon.png": "apple-touch-icon.png",
    "/favicon.ico": "jarvis.ico",
}

_FRAME_HEAD = b"--jarvisframe\r\nContent-Type: image/jpeg\r\nContent-Length: "

_GESTURE_DIR = Path(__file__).parent / "static" / "gesture"
_GESTURE_FILES = {
    "smoothing.js", "gesture-engine.js", "gesture-bridge.js", "deixis.js", "calibration.js",
    # El Kontrolu (/el)
    "hand-features.js", "poses.js", "controller.js", "frame-scheduler.js", "fx-audio.js",
    "fx-particles.js", "fx-fire.js", "fx-seal.js", "fx-planet.js", "fx-burst.js",
    "fx-settings.js", "face-hud.js",
    "shelf-geom.js", "bookshelf.js", "shelf-calib.js", "shelf-drift.js",
    "demo-hands.js", "el-app.js",
}
_MODELS_DIR = Path(__file__).parent / "static" / "models"
_MODEL_TYPES = {".wasm": "application/wasm", ".js": "text/javascript; charset=utf-8",
                ".mjs": "text/javascript; charset=utf-8",
                ".task": "application/octet-stream", ".tflite": "application/octet-stream"}
# JSON govdesi ust siniri (gorseller ham govdeyle gelir, bkz. web/el_api.py)
MAX_JSON_BYTES = 2 * 1024 * 1024
# /api/say kaynak on-ekleri (motor bunlara gore mikrofonu bekletir / bekletmez)
_SAY_SOURCES = {"TELEFON": "[TELEFON]", "EL": "[EL]"}


class _BodyTooLarge(Exception):
    pass


def _cors_allowlist() -> set[str]:
    """CORS'a izin verilen kaynaklar (okul uygulamasi vb.). Env: JARVIS_WEB_CORS_ORIGINS (virgullu)."""
    raw = os.getenv("JARVIS_WEB_CORS_ORIGINS", "")
    extra = {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}
    defaults = {
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:8770", "http://127.0.0.1:8770",
    }
    return defaults | extra


class ConsoleServer:
    def __init__(
        self,
        *,
        outbox_path: Path,
        inbox_path: Path,
        port: int = 8770,
        bind: str = "0.0.0.0",
        token: str = "",
        on_control: "Callable[[str], dict] | None" = None,
        okul_state_path: "Path | None" = None,
        okul_outbox_path: "Path | None" = None,
        team_tts: bool = True,
        remote_desktop: bool = False,
    ) -> None:
        self.outbox = Path(outbox_path)
        self.inbox = Path(inbox_path)
        self.port = int(port)
        self.token = token or ""
        # Token yoksa LAN'a ACMA: yalnizca bu PC (loopback)
        self.bind = (bind or "0.0.0.0") if self.token else "127.0.0.1"
        self._cors = _cors_allowlist()
        self._on_control = on_control
        self.okul_state_path = Path(okul_state_path) if okul_state_path else None
        self.okul_outbox_path = Path(okul_outbox_path) if okul_outbox_path else None
        self._okul_lock = threading.Lock()
        self.team_tts = bool(team_tts)
        self.remote_desktop = bool(remote_desktop)  # web/remote_desktop.py: varsayilan kapali
        self._httpd: ThreadingHTTPServer | None = None

    def pair_page(self) -> str:
        """Telefon uygulamasini tek dokunusla eslestiren sayfa (Tailscale adresi tercih edilir)."""
        import html as _html

        ts, lan = _tailscale_ip(), _lan_ip()
        host = ts or lan
        link = pair_link(host, self.port, self.token)
        svg = _qr_svg(link) or "<p>QR icin: pip install qrcode</p>"
        where = "Tailscale (evde de disarida da calisir)" if ts else "ev Wi-Fi'si (Tailscale bulunamadi)"
        return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>JARVIS · Telefonu eşle</title>
<style>body{{background:#000;color:#ffffffcc;font:16px 'Segoe UI',sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}}
.c{{text-align:center;max-width:420px}}h1{{color:#ff8c42;font-size:22px;letter-spacing:.12em}}
.q{{background:#fff;padding:14px;border-radius:18px;display:inline-block;margin:18px 0}}.q svg{{width:300px;height:300px}}
small{{color:#ffffff70}}code{{color:#ff8c42}}</style></head><body><div class="c">
<h1>JARVIS · TELEFONU EŞLE</h1><p>Telefonun kamerasıyla bu kodu okutun ya da uygulamada <b>Ayarlar → QR ile eşle</b>.</p>
<div class="q">{svg}</div><p>Adres: <code>{_html.escape(host)}:{self.port}</code><br><small>{where}</small></p>
<small>Bu sayfa erişim anahtarını içerir; yalnızca bu bilgisayarda açılır.</small></div></body></html>"""

    # ------------------------------------------------------------------ lifecycle
    def serve_forever(self) -> None:
        server = self
        BUS.state["web_url"] = self.url()
        if not os.getenv("PYTEST_CURRENT_TEST"):
            with contextlib.suppress(Exception):  # yuz kilidi sesi hazir beklesin
                from web.el_api import prewarm_welcome
                prewarm_welcome()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # sessiz
                pass

            def _authed(self) -> bool:
                if not server.token:
                    # token yoksa yalnizca localhost'a izin ver
                    return self.client_address[0] in ("127.0.0.1", "::1", "localhost")
                qs = parse_qs(urlparse(self.path).query)
                given = self.headers.get("X-Jarvis-Key") or qs.get("key", [""])[0]
                return hmac.compare_digest(given.encode("utf-8"), server.token.encode("utf-8"))

            def _cors_headers(self) -> None:
                origin = (self.headers.get("Origin") or "").rstrip("/")
                if origin and origin in server._cors:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")

            def _json(self, code: int, payload) -> None:
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> dict:
                try:
                    n = int(self.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    return {}
                if n > MAX_JSON_BYTES:
                    raise _BodyTooLarge(n)  # okumadan reddet
                try:
                    data = json.loads(self.rfile.read(n) or b"{}")
                except Exception:  # noqa: BLE001
                    return {}
                return data if isinstance(data, dict) else {}

            # --------------------------------------------------------- GET
            def _raw(self, body: bytes, ctype: str, cache: str = "no-cache") -> None:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight (okul kaynaklar arasi)
                self.send_response(204)
                self._cors_headers()
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jarvis-Key")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                # --- kimlik dogrulamasi GEREKMEYEN yollar (PWA kabugu) ---
                if path == "/" or path == "/index.html":
                    self._raw(render_page().encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/manifest.webmanifest":
                    self._raw(render_manifest(server.token).encode("utf-8"),
                              "application/manifest+json; charset=utf-8")
                    return
                if path == "/sw.js":
                    self._raw(PWA_SERVICE_WORKER.encode("utf-8"),
                              "text/javascript; charset=utf-8")
                    return
                if path in _ICON_FILES:
                    fp = ASSETS_DIR / _ICON_FILES[path]
                    if fp.is_file():
                        ctype = "image/x-icon" if fp.suffix == ".ico" else "image/png"
                        self._raw(fp.read_bytes(), ctype, cache="max-age=86400")
                        return
                    self._json(404, {"error": "ikon yok"})
                    return
                if path == "/pair":
                    # Telefon eslestirme QR'i: token icerdigi icin YALNIZCA bu PC'den acilir
                    if self.client_address[0] not in ("127.0.0.1", "::1"):
                        self._json(403, {"error": "eslestirme sayfasi yalnizca PC'den acilir"})
                        return
                    self._raw(server.pair_page().encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path.startswith("/gesture/"):
                    name = path[len("/gesture/"):]
                    if name not in _GESTURE_FILES:
                        self._json(404, {"error": "yok"})
                        return
                    fp = _GESTURE_DIR / name
                    if not fp.is_file():
                        self._json(404, {"error": "yok"})
                        return
                    self._raw(fp.read_bytes(), "text/javascript; charset=utf-8", cache="no-cache")
                    return
                if path.startswith("/models/"):
                    name = path[len("/models/"):]
                    ctype = _MODEL_TYPES.get(Path(name).suffix.lower())
                    if "/" in name or "\\" in name or ".." in name or ctype is None \
                            or not (_MODELS_DIR / name).is_file():
                        self._json(404, {"error": "yok"})
                        return
                    self._raw((_MODELS_DIR / name).read_bytes(), ctype, cache="max-age=604800")
                    return
                if not self._authed():
                    self._json(401, {"error": "gecersiz veya eksik key"})
                    return
                if path == "/hud":
                    self._raw(render_hud_page().encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/el":
                    from web.el_page import render_el_page
                    self._raw(render_el_page().encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path.startswith(("/api/el/", "/api/kitaplik")):
                    from web import el_api
                    el_api.handle_get(self, server, path)
                    return
                if path == "/ekip":
                    self._raw(render_team_page().encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/api/team":
                    from agents.stark_team import public_personas
                    self._json(200, {"personas": public_personas(), "tts": server.team_tts})
                    return
                if path == "/api/state":
                    self._json(200, BUS.snapshot())
                    return
                if path == "/api/events":
                    client = parse_qs(urlparse(self.path).query).get("client", [""])[0]
                    is_phone = client == "phone"
                    is_el = client == "el"
                    if is_phone:
                        PHONE.attach()
                    if is_el:
                        from web.el_api import EL_CLIENTS
                        EL_CLIENTS.attach()
                    try:
                        self._sse()
                    finally:
                        if is_phone:
                            PHONE.detach()
                        if is_el:
                            EL_CLIENTS.detach()
                    return
                if path == "/api/okul/pull":
                    self._json(200, server._okul_pull())
                    return
                if path == "/api/files":
                    self._json(200, {"files": phone_files.list_outbox()})
                    return
                if path == "/api/screen/stream":
                    if not server.remote_desktop:
                        self._json(403, {"error": "uzaktan ekran kapali (.env: JARVIS_REMOTE_DESKTOP=1)"})
                        return
                    self._screen_stream()
                    return
                if path == "/api/files/get":
                    self._download(parse_qs(urlparse(self.path).query).get("name", [""])[0])
                    return
                self._json(404, {"error": "yok"})

            def _download(self, name: str) -> None:
                target = phone_files.outbox_file(name)
                if target is None:
                    self._json(404, {"error": "dosya yok"})
                    return
                size = target.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(target.name))
                self.end_headers()
                try:
                    with target.open("rb") as f:
                        shutil.copyfileobj(f, self.wfile, 256 * 1024)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def _screen_stream(self) -> None:
                from web import remote_desktop

                qs = parse_qs(urlparse(self.path).query)
                fps = float((qs.get("fps") or [remote_desktop.DEFAULT_FPS])[0])
                quality = int((qs.get("q") or [remote_desktop.DEFAULT_QUALITY])[0])
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=jarvisframe")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                client = self.client_address[0]
                remote_desktop.stream_started(client)
                try:
                    for jpg in remote_desktop.frames(fps, quality):
                        self.wfile.write(
                            _FRAME_HEAD + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                        )
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    remote_desktop.stream_stopped(client)

            def _upload(self) -> None:
                name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    saved = phone_files.save_upload(self.rfile, length, name)
                except ValueError as exc:
                    self.close_connection = True  # okunmamis govde kalmis olabilir
                    self._json(400, {"error": str(exc)})
                    return
                except OSError as exc:
                    self.close_connection = True
                    self._json(500, {"error": f"kaydedilemedi: {exc}"})
                    return
                server._append(server.outbox, f"[TELEFON DOSYA] Telefondan dosya geldi: {saved}")
                BUS.push("transcript", {"who": "sys", "text": f"Telefondan dosya: {saved.name}",
                                        "ts": time.time()})
                self._json(200, {"status": "kaydedildi", "name": saved.name})

            def _sse(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = BUS.subscribe()
                try:
                    self.wfile.write(
                        b"data: " + json.dumps(
                            {"kind": "snapshot", "data": BUS.snapshot()}, default=str
                        ).encode("utf-8") + b"\n\n"
                    )
                    self.wfile.flush()
                    last = time.time()
                    while True:
                        drained = False
                        while q:
                            evt = q.popleft()
                            self.wfile.write(
                                b"data: " + json.dumps(evt, ensure_ascii=False, default=str).encode("utf-8")
                                + b"\n\n"
                            )
                            drained = True
                        if drained:
                            self.wfile.flush()
                        if time.time() - last > 20:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            last = time.time()
                        time.sleep(0.4)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    BUS.unsubscribe(q)

            # --------------------------------------------------------- POST
            def do_POST(self) -> None:  # noqa: N802
                if not self._authed():
                    self._json(401, {"error": "gecersiz veya eksik key"})
                    return
                path = urlparse(self.path).path
                if path == "/api/files/upload":
                    self._upload()
                    return
                if path.startswith(("/api/el/", "/api/kitaplik")):
                    from web import el_api
                    try:
                        el_api.handle_post(self, server, path)
                    except _BodyTooLarge:
                        self.close_connection = True
                        self._json(413, {"error": "govde cok buyuk"})
                    return
                try:
                    data = self._read_body()
                except _BodyTooLarge:
                    self.close_connection = True  # okunmamis govde kaldi
                    self._json(413, {"error": "govde cok buyuk"})
                    return
                if path == "/api/say":
                    text = str(data.get("text", "")).strip()
                    if not text:
                        self._json(400, {"error": "text bos"})
                        return
                    source = str(data.get("source", "TELEFON")).strip().upper()
                    prefix = _SAY_SOURCES.get(source)
                    if prefix is None:
                        self._json(400, {"error": f"bilinmeyen source: {source}"})
                        return
                    server._append(server.outbox, f"{prefix} {text}")
                    BUS.push("transcript", {"who": "user", "text": text, "ts": time.time(),
                                            "source": source.lower()})
                    self._json(200, {"status": "iletildi", "source": source.lower()})
                    return
                if path == "/api/task":
                    task = str(data.get("task", "")).strip()
                    if not task:
                        self._json(400, {"error": "task bos"})
                        return
                    rec = {
                        "id": f"web{int(time.time())}",
                        "agent": str(data.get("agent", "auto")),
                        "task": task,
                        "source": "web",
                    }
                    server._append(server.inbox, json.dumps(rec, ensure_ascii=False))
                    self._json(200, {"status": "kuyruga alindi", "id": rec["id"]})
                    return
                if path == "/api/phone-event":
                    app = str(data.get("app", "telefon"))
                    text = str(data.get("text", "")).strip()
                    if text:
                        server._append(server.outbox, f"[TELEFON BILDIRIMI] {app}: {text}")
                        BUS.push("transcript", {"who": "sys", "text": f"Telefon · {app}: {text}",
                                                "ts": time.time()})
                    self._json(200, {"status": "alindi"})
                    return
                if path == "/api/control":
                    action = str(data.get("action", "")).strip().lower()
                    if action not in ("mic_on", "mic_off", "away_on", "away_off", "wake_on", "wake_off",
                                      "interrupt"):
                        self._json(400, {"error": f"bilinmeyen action: {action}"})
                        return
                    result = {"status": "uygulandi", "action": action}
                    if server._on_control is not None:
                        try:
                            result.update(server._on_control(action) or {})
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(f"on_control hatasi: {exc!r}")
                            self._json(500, {"error": str(exc)})
                            return
                    else:
                        result["note"] = "kontrol geri cagrimi bagli degil (arayuz calismiyor)"
                    away = action == "away_on"
                    if action in ("away_on", "away_off"):
                        BUS.state["away"] = away
                        BUS.push("control_state", {"away": away})
                    elif action in ("mic_on", "mic_off"):
                        BUS.push("control_state", {"mic": action == "mic_on"})
                    elif action in ("wake_on", "wake_off") and "error" not in result:
                        BUS.push("control_state", {"wake": action == "wake_on"})
                    self._json(200, result)
                    return
                if path == "/api/remote/input":
                    if not server.remote_desktop:
                        self._json(403, {"error": "uzaktan kontrol kapali (.env: JARVIS_REMOTE_DESKTOP=1)"})
                        return
                    from web.remote_desktop import handle_input
                    self._json(200, handle_input(data))
                    return
                if path == "/api/phone-result":
                    req_id = str(data.get("id", "")).strip()
                    if not req_id:
                        self._json(400, {"error": "id bos"})
                        return
                    if data.get("ok"):
                        reply = {"status": "ok", "result": data.get("result")}
                    else:
                        reply = {"error": str(data.get("error") or "telefonda basarisiz")}
                    if not PHONE.resolve(req_id, reply):
                        self._json(404, {"error": "istek bulunamadi (zaman asimina ugramis olabilir)"})
                        return
                    self._json(200, {"status": "alindi"})
                    return
                if path == "/api/confirm":
                    conf_id = str(data.get("id", "")).strip()
                    approve = bool(data.get("approve"))
                    if not conf_id:
                        self._json(400, {"error": "id bos"})
                        return
                    ok = REGISTRY.resolve(conf_id, approve)
                    if not ok:
                        self._json(404, {"error": "onay istegi bulunamadi (zaman asimina ugramis olabilir)"})
                        return
                    self._json(200, {"status": "cozuldu", "id": conf_id, "approved": approve})
                    return
                if path == "/api/team/ask":
                    code, payload = server._team_ask(data)
                    self._json(code, payload)
                    return
                if path == "/api/team/council/turn":
                    code, payload = server._team_council_turn(data)
                    self._json(code, payload)
                    return
                if path == "/api/team/council/next":
                    code, payload = server._team_council_next(data)
                    self._json(code, payload)
                    return
                if path == "/api/okul/push":
                    self._json(200, server._okul_push(data))
                    return
                if path == "/api/gesture":
                    gesture = str(data.get("gesture", "")).strip().lower()
                    part = str(data.get("part", "")).strip()
                    if not gesture:
                        self._json(400, {"error": "gesture bos"})
                        return
                    BUS.push("ui.gesture", {"gesture": gesture, "part": part,
                                             "ts": data.get("ts") or time.time()})
                    if gesture != "select" or not part:
                        self._json(200, {"status": "kaydedildi"})
                        return
                    rec = {
                        "id": f"gesture{int(time.time() * 1000)}",
                        "agent": "auto",
                        "task": f"HUD'da secilen parca hakkinda 1-2 cumlelik kisa, sozlu bir aciklama ver: {part}",
                        "source": "gesture",
                    }
                    server._append(server.inbox, json.dumps(rec, ensure_ascii=False))
                    self._json(200, {"status": "kuyruga alindi", "id": rec["id"]})
                    return
                self._json(404, {"error": "yok"})

        self._httpd = ThreadingHTTPServer((self.bind, self.port), Handler)
        logger.success(f"Web konsolu: {self.url(masked=True)}")
        try:
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Web konsolu durdu: {exc!r}")

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ okul koprusu
    @staticmethod
    def _write_json_atomic(path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                json.dump(payload, h, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _okul_push(self, data: dict) -> dict:
        """okul'un gonderdigi tam durumu diske yazar (localStorage aynasi)."""
        if self.okul_state_path is None:
            return {"error": "okul koprusu yapilandirilmamis"}
        if not isinstance(data, dict) or "data" not in data:
            return {"error": "beklenen govde: {app, version, data:{...}}"}
        record = {
            "receivedAt": time.time(),
            "exportedAt": data.get("exportedAt"),
            "data": data.get("data") or {},
        }
        try:
            with self._okul_lock:
                self._write_json_atomic(self.okul_state_path, record)
        except OSError as exc:
            logger.error(f"okul durumu yazilamadi: {exc}")
            return {"error": str(exc)}
        keys = len(record["data"])
        BUS.push("okul_sync", {"keys": keys, "ts": record["receivedAt"]})
        logger.debug(f"okul durumu alindi ({keys} anahtar).")
        return {"status": "alindi", "keys": keys}

    def _team_ask(self, data: dict) -> tuple[int, dict]:
        """POST /api/team/ask - Stark Ekibi'nden bir persona'ya soru (yanit + ses)."""
        from agents import stark_team

        key = str(data.get("persona", "")).strip().lower()
        text = str(data.get("text", "")).strip()[: stark_team.MAX_TEXT]
        persona = stark_team.PERSONAS.get(key)
        if persona is None:
            return 400, {"error": f"bilinmeyen persona: {key}"}
        if not text:
            return 400, {"error": "text bos"}
        BUS.push("transcript", {"who": "user", "text": f"[{persona.name}] {text}", "ts": time.time()})
        if persona.provider == "live":
            # native-audio model metinle cagrilamaz: canli beyne kopru, kendi sesiyle konusur
            self._append(self.outbox, f"[TELEFON] {text}")
            return 200, {"via": "live", "persona": key}
        try:
            out = stark_team.run_sync(stark_team.answer(
                key, text, data.get("history"), tts=self.team_tts,
                consult=bool(data.get("consult", True)), allow_paid=bool(data.get("allow_paid")),
            ))
        except Exception as exc:  # noqa: BLE001 - zaman asimi vb.
            logger.warning(f"/api/team/ask {key}: {exc!r}")
            return 504, {"error": f"{persona.name} zamaninda yanit vermedi"}
        for c in out.get("consults", []):
            if c.get("text"):
                to = stark_team.PERSONAS.get(c["to"])
                BUS.push("transcript", {"who": "sys", "text": f"{persona.name} → {to.name if to else c['to']}: "
                                        f"{c['question']} | {c['text']}", "ts": time.time()})
        if out.get("text"):
            BUS.push("transcript", {"who": "sys", "text": f"{persona.name}: {out['text']}",
                                    "ts": time.time()})
        return 200, {"persona": key, **out}

    def _team_council_turn(self, data: dict) -> tuple[int, dict]:
        """POST /api/team/council/turn - toplanti masasinda tek bir uyenin sirasi."""
        from agents import stark_team

        key = str(data.get("persona", "")).strip().lower()
        topic = str(data.get("topic", "")).strip()[: stark_team.MAX_TEXT]
        persona = stark_team.PERSONAS.get(key)
        if persona is None or persona.provider == "live":
            return 400, {"error": f"toplantiya katilamaz: {key}"}
        if not topic:
            return 400, {"error": "topic bos"}
        final = bool(data.get("final"))
        try:
            out = stark_team.run_sync(stark_team.council_turn(
                key, topic, data.get("transcript"), final=final, tts=self.team_tts))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"/api/team/council/turn {key}: {exc!r}")
            return 504, {"error": f"{persona.name} zamaninda yanit vermedi"}
        if out.get("text"):
            BUS.push("transcript", {"who": "sys", "text": f"[TOPLANTI] {persona.name}: {out['text']}",
                                    "ts": time.time()})
        return 200, {"persona": key, "final": final, **out}

    def _team_council_next(self, data: dict) -> tuple[int, dict]:
        """POST /api/team/council/next - toplantida sozu kime verecegini secer (sabit sira yok)."""
        from agents import stark_team

        topic = str(data.get("topic", "")).strip()[: stark_team.MAX_TEXT]
        members = data.get("members")
        if not topic:
            return 400, {"error": "topic bos"}
        if not isinstance(members, list) or not members:
            return 400, {"error": "members bos"}
        last = str(data.get("last") or "").strip().lower() or None
        try:
            out = stark_team.run_sync(stark_team.next_speaker(
                topic, data.get("transcript"), [str(m).lower() for m in members], last))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"/api/team/council/next: {exc!r}")
            return 504, {"error": "konusmaci secilemedi"}
        return 200, out

    def _okul_pull(self) -> dict:
        """JARVIS'in okul'a iletecegi bekleyen degisiklikleri dondurur ve kuyrugu bosaltir."""
        if self.okul_outbox_path is None:
            return {"ops": []}
        with self._okul_lock:
            ops: list = []
            try:
                if self.okul_outbox_path.is_file():
                    ops = json.loads(self.okul_outbox_path.read_text(encoding="utf-8")) or []
            except (OSError, ValueError) as exc:
                logger.warning(f"okul outbox okunamadi: {exc}")
                ops = []
            if ops:
                with contextlib.suppress(OSError):
                    self._write_json_atomic(self.okul_outbox_path, [])
        return {"ops": ops, "ts": time.time()}

    # ------------------------------------------------------------------ helpers
    def _append(self, path: Path, line: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as h:
                h.write(" ".join(line.split()).strip() + "\n")
        except OSError as exc:
            logger.error(f"web konsolu yazamadi: {exc}")

    def url(self, masked: bool = False) -> str:
        """Konsol adresi. `masked=True` token'i gizler - log dosyalarina HER ZAMAN maskeli yazilir."""
        ip = _lan_ip() if self.bind == "0.0.0.0" else self.bind
        tok = f"?key={'***' if masked else self.token}" if self.token else ""
        return f"http://{ip}:{self.port}{tok}"


def _tailscale_ip() -> str:
    """Tailscale arayuzunun IPv4'u (100.64.0.0/10); yoksa bos."""
    import ipaddress

    try:
        import psutil

        net = ipaddress.ip_network("100.64.0.0/10")
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and ipaddress.ip_address(a.address) in net:
                    return a.address
    except Exception:  # noqa: BLE001
        pass
    return ""


def pair_link(host: str, port: int, token: str) -> str:
    from urllib.parse import urlencode

    return "jarvis://pair?" + urlencode({"host": host, "port": port, "key": token})


def _qr_svg(text: str) -> str:
    """QR kodu satir ici SVG (qrcode paketi; yoksa bos)."""
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return ""
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    return img.to_string(encoding="unicode")


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
