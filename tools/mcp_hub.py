"""MCP istemcisi: JARVIS'i herhangi bir Model Context Protocol sunucusuna baglar.

Sunucular `config/mcp_servers.json` dosyasinda Claude Desktop bicimiyle tanimlanir:

    {"mcpServers": {
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                   "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}, "confirm": "write"},
        "notion": {"url": "https://mcp.notion.com/mcp", "headers": {...}, "confirm": "all"}
    }}

Sesli beyne yuzlerce arac yuklenmez; uc gecit araci vardir:
`mcp_servers` -> `mcp_list_tools` -> `mcp_call`. Baglantilar tembel acilir ve
`core.async_worker` loop'unda kalici tutulur.

confirm: "none" | "write" (varsayilan: yazan/silen/gonderen araclar onaya duser) | "all".
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import APP_DIR, get_settings
from core.async_worker import get_worker

CONNECT_TIMEOUT_S = 60.0
CALL_TIMEOUT_S = 120.0
MAX_RESULT_CHARS = 6000
MAX_LISTED_TOOLS = 25

_WRITE_WORDS = {
    "create", "update", "delete", "remove", "send", "write", "push", "post", "merge", "edit",
    "move", "rename", "upload", "insert", "set", "add", "archive", "close", "publish",
    "execute", "exec", "run", "drop", "replace", "patch", "put", "fork", "comment", "reply",
    "kill", "trash", "submit", "pay", "transfer", "invite", "share", "assign",
}
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _name_tokens(tool: str) -> set[str]:
    """'createIssue' / 'delete_file' / 'git-push' -> {'create','issue'} ..."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", tool)
    return {t.lower() for t in re.split(r"[\s_\-.:/]+", spaced) if t}


def _expand(value: str) -> str:
    return _ENV_REF.sub(lambda m: os.getenv(m.group(1), ""), str(value))


@dataclass
class ServerSpec:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    confirm: str = "write"
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    description: str = ""
    disabled: bool = False

    @classmethod
    def from_dict(cls, name: str, raw: dict[str, Any]) -> ServerSpec:
        env = raw.get("env")
        return cls(
            name=name,
            command=_expand(raw.get("command", "")),
            args=[_expand(a) for a in raw.get("args", [])],
            env={k: _expand(v) for k, v in env.items()} if isinstance(env, dict) else None,
            cwd=_expand(raw["cwd"]) if raw.get("cwd") else None,
            url=_expand(raw.get("url", "")),
            headers={k: _expand(v) for k, v in (raw.get("headers") or {}).items()},
            confirm=str(raw.get("confirm", "write")).lower(),
            allow=list(raw.get("allow", [])),
            deny=list(raw.get("deny", [])),
            description=str(raw.get("description", "")),
            disabled=bool(raw.get("disabled", False)),
        )

    def tool_allowed(self, tool: str) -> bool:
        if tool in self.deny:
            return False
        return not self.allow or tool in self.allow


def load_specs(path: Path | None = None) -> dict[str, ServerSpec]:
    path = Path(path or get_settings().mcp_config_file)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[MCP] {path} okunamadi: {exc}")
        return {}
    servers = data.get("mcpServers", data.get("servers", {})) or {}
    return {
        name: ServerSpec.from_dict(name, raw)
        for name, raw in servers.items()
        if isinstance(raw, dict)
    }


class _Connection:
    """Tek sunucu baglantisi. anyio iptal kapsamlari ayni gorevde acilip
    kapanmak zorunda oldugundan baglanti kendi uzun omurlu gorevinde yasar."""

    def __init__(self, spec: ServerSpec) -> None:
        self.spec = spec
        self.session: Any = None
        self.tools: list[Any] = []
        self.error: str = ""
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def alive(self) -> bool:
        return self.session is not None and self._task is not None and not self._task.done()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.spec.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT_S)
        except asyncio.TimeoutError:
            self.error = f"{CONNECT_TIMEOUT_S:.0f} sn icinde baglanamadi"
            await self.stop()
        if self.session is None and not self.error:
            self.error = "baglanti kurulamadi"

    async def _run(self) -> None:
        from mcp import ClientSession

        spec = self.spec
        try:
            async with AsyncExitStack() as stack:
                if spec.url:
                    from mcp.client.streamable_http import streamablehttp_client

                    read, write, _ = await stack.enter_async_context(
                        streamablehttp_client(spec.url, headers=spec.headers or None)
                    )
                else:
                    from mcp.client.stdio import StdioServerParameters, stdio_client

                    log_dir = APP_DIR / "data" / "logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    errlog = stack.enter_context(
                        (log_dir / f"mcp_{spec.name}.log").open("a", encoding="utf-8")
                    )
                    params = StdioServerParameters(
                        command=spec.command, args=spec.args, env=spec.env, cwd=spec.cwd
                    )
                    read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.tools = list((await session.list_tools()).tools)
                self.session = session
                logger.info(f"[MCP] {spec.name} bagli ({len(self.tools)} arac)")
                self._ready.set()
                await self._stop.wait()
        except Exception as exc:  # noqa: BLE001 - sunucu hatasi JARVIS'i cokertmez
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning(f"[MCP] {spec.name} baglanti hatasi: {self.error}")
        finally:
            self.session = None
            self._ready.set()

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, 10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                self._task.cancel()


class MCPHub:
    def __init__(self, config_file: Path | None = None) -> None:
        self._config_file = config_file
        self._specs: dict[str, ServerSpec] | None = None
        self._conns: dict[str, _Connection] = {}
        self._lock: asyncio.Lock | None = None
        self._registered = False

    # ------------------------------------------------------------ config
    @property
    def specs(self) -> dict[str, ServerSpec]:
        if self._specs is None:
            self._specs = load_specs(self._config_file)
        return self._specs

    def reload(self) -> None:
        self._specs = None

    def needs_confirm(self, server: str, tool: str) -> bool:
        spec = self.specs.get(server)
        if spec is None:
            return False
        if spec.confirm == "none":
            return False
        if spec.confirm == "all":
            return True
        conn = self._conns.get(server)
        for t in (conn.tools if conn else []):
            if t.name == tool and t.annotations is not None:
                if t.annotations.readOnlyHint is True:
                    return False
                if t.annotations.destructiveHint is True:
                    return True
        return bool(_name_tokens(tool) & _WRITE_WORDS)

    # ------------------------------------------------------------ async core
    async def _get(self, server: str) -> _Connection:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            conn = self._conns.get(server)
            if conn is not None and conn.alive:
                return conn
            if conn is not None:
                await conn.stop()
            spec = self.specs[server]
            conn = _Connection(spec)
            await conn.start()
            self._conns[server] = conn
            return conn

    async def _list_tools(self, server: str) -> list[Any]:
        conn = await self._get(server)
        if conn.session is None:
            raise ConnectionError(conn.error or "baglanti yok")
        return conn.tools

    async def _call(self, server: str, tool: str, args: dict[str, Any]) -> Any:
        from datetime import timedelta

        for attempt in (1, 2):
            conn = await self._get(server)
            if conn.session is None:
                raise ConnectionError(conn.error or "baglanti yok")
            try:
                return await conn.session.call_tool(
                    tool, args, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_S)
                )
            except Exception as exc:  # noqa: BLE001
                if attempt == 2 or conn.alive:
                    raise
                logger.info(f"[MCP] {server} baglantisi koptu, yeniden deneniyor: {exc!r}")
        raise RuntimeError("ulasilamaz")

    async def aclose(self) -> None:
        for conn in list(self._conns.values()):
            await conn.stop()
        self._conns.clear()

    def _submit(self, coro: Any, timeout: float) -> Any:
        worker = get_worker()
        if not self._registered:
            worker.on_shutdown(self.aclose)
            self._registered = True
        return worker.submit(coro, timeout)

    # ------------------------------------------------------------ sync API
    def servers(self) -> dict[str, Any]:
        if not get_settings().mcp_enabled:
            return {"error": "MCP kapali (.env JARVIS_MCP=false)."}
        if not self.specs:
            return {
                "servers": [],
                "hint": "Hic MCP sunucusu tanimli degil. config/mcp_servers.example.json'u "
                        "config/mcp_servers.json olarak kopyalayip duzenleyin.",
            }
        out = []
        for name, spec in self.specs.items():
            conn = self._conns.get(name)
            out.append({
                "name": name,
                "description": spec.description,
                "type": "http" if spec.url else "stdio",
                "status": ("devre disi" if spec.disabled else
                           "bagli" if conn and conn.alive else
                           f"hata: {conn.error}" if conn and conn.error else "bagli degil (ilk kullanimda baglanir)"),
                "tool_count": len(conn.tools) if conn else None,
                "confirm": spec.confirm,
            })
        return {"servers": out}

    def _check_server(self, server: str) -> dict[str, Any] | None:
        if not get_settings().mcp_enabled:
            return {"error": "MCP kapali (.env JARVIS_MCP=false)."}
        spec = self.specs.get(server)
        if spec is None:
            return {"error": f"Bilinmeyen MCP sunucusu: '{server}'. Mevcut: {', '.join(self.specs) or 'yok'}"}
        if spec.disabled:
            return {"error": f"'{server}' devre disi."}
        return None

    def ensure_connected(self, server: str) -> dict[str, Any] | None:
        """Sunucuya baglanir (arac anotasyonlari onay karari icin gerekir); hata varsa dondurur."""
        server = (server or "").strip()
        if (err := self._check_server(server)) is not None:
            return err
        try:
            self._submit(self._list_tools(server), CONNECT_TIMEOUT_S + 10)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"'{server}' baglanamadi: {exc}"}
        return None

    def list_tools(self, server: str, query: str = "") -> dict[str, Any]:
        server = (server or "").strip()
        if (err := self._check_server(server)) is not None:
            return err
        try:
            tools = self._submit(self._list_tools(server), CONNECT_TIMEOUT_S + 10)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"'{server}' baglanamadi: {exc}"}
        spec = self.specs[server]
        q = (query or "").lower().strip()
        rows = []
        for t in tools:
            if not spec.tool_allowed(t.name):
                continue
            desc = " ".join((t.description or "").split())
            if q and q not in t.name.lower() and q not in desc.lower():
                continue
            schema = t.inputSchema or {}
            props = schema.get("properties", {}) or {}
            required = set(schema.get("required", []) or [])
            params = {
                p: f"{(v or {}).get('type', 'any')}{' (zorunlu)' if p in required else ''}"
                   + (f" - {(v or {}).get('description')[:80]}" if (v or {}).get("description") else "")
                for p, v in props.items()
            }
            rows.append({
                "name": t.name,
                "description": desc[:300],
                "params": params,
                "needs_confirm": self.needs_confirm(server, t.name),
            })
        total = len(rows)
        if total <= MAX_LISTED_TOOLS:
            return {"server": server, "total": total, "tools": rows}
        # Cok arac: hepsinin ADI + ilk sayfanin ayrintisi; model dogru araci secip
        # query=<ad> ile parametrelerini ister.
        return {"server": server, "total": total,
                "all_tool_names": [r["name"] for r in rows],
                "tools": rows[:MAX_LISTED_TOOLS],
                "note": f"Ayrinti ilk {MAX_LISTED_TOOLS} arac icin. Diger araclarin parametreleri icin "
                        "mcp_list_tools(server, query=<arac adi>) cagir."}

    def call(self, server: str, tool: str, arguments_json: str = "") -> dict[str, Any]:
        server, tool = (server or "").strip(), (tool or "").strip()
        if (err := self._check_server(server)) is not None:
            return err
        if not tool:
            return {"error": "'tool' zorunlu."}
        if not self.specs[server].tool_allowed(tool):
            return {"error": f"'{tool}' araci bu sunucu icin izinli degil."}
        args = parse_arguments(arguments_json)
        if isinstance(args, str):
            return {"error": args}
        try:
            result = self._submit(self._call(server, tool, args), CONNECT_TIMEOUT_S + CALL_TIMEOUT_S + 10)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        return format_result(result)


def parse_arguments(arguments_json: Any) -> dict[str, Any] | str:
    if isinstance(arguments_json, dict):
        return arguments_json
    raw = (arguments_json or "").strip()
    if not raw:
        return {}
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"arguments_json gecerli JSON degil: {exc}"
    if not isinstance(args, dict):
        return "arguments_json bir JSON nesnesi olmali (orn. {\"path\": \"C:/\"})."
    return args


def format_result(result: Any) -> dict[str, Any]:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", "")
        if kind == "text":
            parts.append(item.text)
        elif kind == "image":
            parts.append(f"[gorsel: {getattr(item, 'mimeType', '?')}]")
        elif kind == "resource":
            res = getattr(item, "resource", None)
            parts.append(getattr(res, "text", None) or f"[kaynak: {getattr(res, 'uri', '?')}]")
        else:
            parts.append(f"[{kind}]")
    structured = getattr(result, "structuredContent", None)
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    text = "\n".join(parts)
    truncated = len(text) > MAX_RESULT_CHARS
    out: dict[str, Any] = {"result": text[:MAX_RESULT_CHARS] + (" …[kirpildi]" if truncated else "")}
    if getattr(result, "isError", False):
        out = {"error": out["result"] or "MCP araci hata dondurdu"}
    return out


_hub: MCPHub | None = None


def get_hub() -> MCPHub:
    global _hub
    if _hub is None:
        _hub = MCPHub()
    return _hub


# ------------------------------------------------------------------ arac yuzleri

def mcp_servers() -> dict[str, Any]:
    """Tanimli MCP sunucularini (GitHub, Notion, takvim...) ve baglanti durumlarini listeler."""
    return get_hub().servers()


def mcp_list_tools(server: str, query: str = "") -> dict[str, Any]:
    """Bir MCP sunucusundaki araclari ad, aciklama ve parametreleriyle listeler. query ile filtreler."""
    return get_hub().list_tools(server, query)


def mcp_call_readonly(server: str, tool: str, arguments_json: str = "") -> dict[str, Any]:
    """Bir MCP sunucusundaki araci cagirir. arguments_json, aracin parametrelerini iceren JSON nesnesidir
    (orn. {"query": "x"}). Yazan/silen/gonderen araclar yalnizca sesli JARVIS onayiyla calisir."""
    hub = get_hub()
    if (err := hub.ensure_connected(server)) is not None:
        return err
    if hub.needs_confirm((server or "").strip(), (tool or "").strip()):
        return {"error": "Bu MCP islemi kullanici onayi ister; ajan calistiramaz. "
                         "Kullaniciya JARVIS'e sesli olarak yaptirmasini oner."}
    return hub.call(server, tool, arguments_json)


mcp_call_readonly.__name__ = "mcp_call"
