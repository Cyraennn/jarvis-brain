"""FastAPI uclari: GET /health, POST /command, WS /ws.

Tum uclar kimlik dogrulamali: HTTP'de `X-Token` basligi, WebSocket'te ilk mesajdaki
`token` (deger: .env JARVIS_TOKEN, karsilastirma `secrets.compare_digest`).
OpenAPI/dokumantasyon sayfalari kapali (saldiri yuzeyi olmasin).
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server import __version__


class CommandIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


def create_app(runtime: Any) -> FastAPI:
    app = FastAPI(title="JARVIS", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None)

    def require_token(x_token: str | None = Header(default=None, alias="X-Token")) -> None:
        if not runtime.check_token(x_token):
            raise HTTPException(status_code=401, detail="gecersiz veya eksik X-Token")

    @app.get("/health", dependencies=[Depends(require_token)])
    async def health(probe: bool = False) -> dict[str, Any]:
        if probe:
            await runtime.run_probe()
        return runtime.health()

    @app.post("/command", dependencies=[Depends(require_token)])
    async def command(body: CommandIn) -> JSONResponse:
        result = await runtime.command(body.text)
        if not result.ok and "oturum" in (result.error or "").lower():
            return JSONResponse(status_code=503, content=result.as_dict())
        return JSONResponse(status_code=200 if result.ok else 504, content=result.as_dict())

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await runtime.handle_ws(websocket)

    return app
