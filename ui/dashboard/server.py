"""Decision Pipeline panosu - FastAPI.

    GET  /dashboard            tek sayfa (index.html + app.js + style.css)
    GET  /api/info             modeller (aktif/pasif, fiyat), esikler, gorev tipleri
    GET  /api/decisions?limit= routing.jsonl'daki son kayitlar (REPLAY modu)
    WS   /ws/decisions         canli kararlar (router.events.BUS)

Varsayilan olarak yalnizca 127.0.0.1'e baglanir (kimlik dogrulamasi yok; kararlarda istek
metinleri gecer). Orkestrator acilirken `start_dashboard` ile kendi thread'inde baslar.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, Response
from loguru import logger

VERSION = "router 1.1"
_STATIC = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
           "style.css": "text/css; charset=utf-8"}
_started = False
_start_lock = threading.Lock()


def static_dir() -> Path:
    from config.settings import RESOURCE_DIR

    bundled = Path(RESOURCE_DIR) / "ui" / "dashboard"
    return bundled if (bundled / "index.html").exists() else Path(__file__).resolve().parent


def read_decisions(path: Path | None, limit: int = 500) -> list[dict[str, Any]]:
    """routing.jsonl'in son `limit` satiri (bozuk satirlar atlanir)."""
    if path is None or not Path(path).exists():
        return []
    tail: deque[str] = deque(maxlen=max(1, min(int(limit), 5000)))
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                tail.append(line)
    rows = []
    for line in tail:
        with contextlib.suppress(json.JSONDecodeError):
            rows.append(json.loads(line))
    return rows


def info_payload(settings: Any) -> dict[str, Any]:
    from router import get_active
    from router.registry import ModelRegistry

    router = get_active()
    try:
        registry = router.registry if router is not None else ModelRegistry.load(settings.router_config_path)
    except Exception as exc:  # noqa: BLE001
        return {"version": VERSION, "error": f"models.yaml okunamadi: {exc}", "models": []}
    models = [
        {"id": m.id, "provider": m.provider, "speed": m.speed, "cost": m.cost, "active": m.active,
         "status": m.status, "reason": m.reason, "routable": m.routable,
         "price": registry.pricing.get(m.id)}
        for m in registry.models.values()
    ]
    return {
        "version": VERSION,
        "router_active": router is not None,
        "classifier_ready": bool(router and router.classifier and router.classifier.ready),
        "thresholds": {"task": registry.task_threshold, "difficulty": registry.difficulty_threshold,
                       "agent": registry.agent_threshold},
        "task_types": registry.task_types,
        "models": models,
        "chains": registry.chains,
    }


def create_app(settings: Any) -> FastAPI:
    # Not: FastAPI tipleri modul duzeyinde ice aktarilir; `from __future__ import annotations`
    # ile yerel ice aktarma WebSocket parametresini sorgu parametresi sandirir.
    from router.events import BUS

    app = FastAPI(title="JARVIS Decision Pipeline", docs_url=None, redoc_url=None, openapi_url=None)
    root = static_dir()

    def _file(name: str) -> Response:
        path = root / name
        if name not in _STATIC or not path.exists():
            return Response(status_code=404)
        return Response(path.read_bytes(), media_type=_STATIC[name],
                        headers={"Cache-Control": "no-store"})

    @app.get("/")
    async def index_redirect() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    @app.get("/dashboard")
    @app.get("/dashboard/")
    async def page() -> Response:
        return _file("index.html")

    @app.get("/dashboard/{name}")
    async def asset(name: str) -> Response:
        return _file(name)

    @app.get("/api/info")
    async def info() -> JSONResponse:
        return JSONResponse(info_payload(settings))

    @app.get("/api/decisions")
    async def decisions(limit: int = 500) -> JSONResponse:
        rows = await asyncio.to_thread(read_decisions, getattr(settings, "routing_log_path", None), limit)
        return JSONResponse({"rows": rows})

    @app.websocket("/ws/decisions")
    async def ws_decisions(ws: WebSocket) -> None:
        await ws.accept()
        queue = BUS.subscribe()
        await ws.send_json({"kind": "hello", "version": VERSION})

        async def drain_client() -> None:   # istemci kapaninca ayrilmayi fark et
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                while True:
                    await ws.receive_text()

        reader = asyncio.create_task(drain_client())
        try:
            while not reader.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    event = {"kind": "ping"}
                await ws.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            BUS.unsubscribe(queue)
            reader.cancel()

    return app


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) != 0


def start_dashboard(settings: Any) -> str | None:
    """Sureç basina BIR kez: uvicorn'u daemon thread'de baslatir. URL'yi (ya da None) doner."""
    global _started
    with _start_lock:
        if _started:
            return None
        host, port = settings.dashboard_host, int(settings.dashboard_port)
        if not _port_free(host, port):
            logger.warning(f"[pano] Port {port} dolu; Decision Pipeline baslatilmadi.")
            return None
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(create_app(settings), host=host, port=port,
                                               log_level="warning", lifespan="off",
                                               # pythonw'de stdout/stderr yok: uvicorn'un kendi log
                                               # ayari 'formatter default' hatasi verir -> kapali
                                               log_config=None, access_log=False))
        # uvicorn ana thread disinda sinyal yakalamaz (capture_signals) - JARVIS'in kapanisina karismaz
        threading.Thread(target=server.run, name="decision-dashboard", daemon=True).start()
        _started = True
        url = f"http://127.0.0.1:{port}/dashboard/"
        logger.success(f"[pano] Decision Pipeline: {url}")
        return url
