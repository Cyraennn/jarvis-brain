"""Yerel model yedegi (Ollama) - bulut zinciri tamamen dusunce son care.

`agents/genai_util.generate_with_retry` son Gemini modeli de kalici olarak dustugunde
istegi buraya devreder. google-genai istegi (contents + GenerateContentConfig) Ollama'nin
yerel `/api/chat` bicimine cevrilir, yanit da `types.GenerateContentResponse`'a geri
cevrilir; boylece cagiranlar (ajan arac dongusu dahil) farki gormez.

Yerel `/api/chat` kullanilir (OpenAI uyumlu `/v1` degil): `options.num_ctx` ve `keep_alive`
yalnizca orada var; Ollama'nin varsayilan 2048 baglami aracli ajan prompt'larini keser.

Desteklenmeyenler (cagiran orijinal hatayi alir): ses/gorsel iceren istekler
(`inline_data` / `file_data`). Google Search araci atilir, modele "web aramasi yok" denir.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any

import httpx
from google.genai import types
from loguru import logger

PROVIDER = "ollama"
_HEALTH_TTL_S = 30.0
_NO_SEARCH_NOTE = (
    "[YEREL MOD] Su an cevrimdisi yerel modelsin; web aramasi YOK. Guncel bilgi "
    "(haber, skor, fiyat, hava) uydurma - bilmiyorsan acikca soyle."
)


class LocalLLMError(RuntimeError):
    """Yerel model yanit veremedi (servis kapali / model yok / zaman asimi)."""


def model_label(model: str) -> str:
    return f"{PROVIDER}/{model}"


# ------------------------------------------------------------------ istek cevirisi
def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _lower_types(node: Any) -> Any:
    """Gemini Schema dokumundeki "STRING"/"OBJECT" gibi tipleri JSON Schema'ya cevirir."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, val in node.items():
            if key == "type" and isinstance(val, str):
                out[key] = val.lower()
            elif key == "nullable":
                continue  # JSON Schema'da yok; zorunlu olmamasi yeterli
            else:
                out[key] = _lower_types(val)
        return out
    if isinstance(node, list):
        return [_lower_types(v) for v in node]
    return node


def _tool_schemas(config: types.GenerateContentConfig | None) -> tuple[list[dict], bool]:
    """(Ollama `tools` listesi, google_search istenmis mi)."""
    tools: list[dict] = []
    wanted_search = False
    for tool in _as_list(getattr(config, "tools", None)):
        if getattr(tool, "google_search", None) is not None or getattr(
            tool, "google_search_retrieval", None
        ) is not None:
            wanted_search = True
        for fd in _as_list(getattr(tool, "function_declarations", None)):
            params = getattr(fd, "parameters_json_schema", None)
            if params is None and getattr(fd, "parameters", None) is not None:
                params = _lower_types(fd.parameters.model_dump(exclude_none=True, mode="json"))
            tools.append({
                "type": "function",
                "function": {
                    "name": fd.name,
                    "description": fd.description or fd.name,
                    "parameters": params or {"type": "object", "properties": {}},
                },
            })
    return tools, wanted_search


def _system_text(config: types.GenerateContentConfig | None) -> str:
    si = getattr(config, "system_instruction", None)
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    parts = getattr(si, "parts", None) or _as_list(si)
    return "\n".join(
        (p if isinstance(p, str) else (getattr(p, "text", None) or "")) for p in parts
    ).strip()


def _iter_contents(contents: Any) -> list[tuple[str, list[Any]]]:
    """contents'i (rol, parca listesi) dizisine normalize eder."""
    out: list[tuple[str, list[Any]]] = []
    loose: list[Any] = []  # ust duzeyde duz str/Part'lar tek kullanici turu olur
    for item in _as_list(contents):
        if isinstance(item, types.Content):
            if loose:
                out.append(("user", loose))
                loose = []
            out.append((item.role or "user", list(item.parts or [])))
        else:
            loose.append(item)
    if loose:
        out.append(("user", loose))
    return out


def supports(contents: Any) -> bool:
    """Yerel model metin+arac isteklerini karsilar; ses/gorsel iceren istekleri DEGIL."""
    for _, parts in _iter_contents(contents):
        for part in parts:
            if getattr(part, "inline_data", None) is not None or getattr(
                part, "file_data", None
            ) is not None:
                return False
    return True


def to_ollama(contents: Any, config: types.GenerateContentConfig | None) -> dict[str, Any]:
    """google-genai istegini Ollama `/api/chat` govdesine cevirir (model/options haric)."""
    tools, wanted_search = _tool_schemas(config)
    system = _system_text(config)
    if wanted_search:
        system = f"{system}\n\n{_NO_SEARCH_NOTE}".strip()

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})

    for role, parts in _iter_contents(contents):
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, str):
                texts.append(part)
                continue
            fr = getattr(part, "function_response", None)
            if fr is not None:
                messages.append({
                    "role": "tool",
                    "tool_name": fr.name,
                    "content": json.dumps(fr.response, ensure_ascii=False, default=str)[:8000],
                })
                continue
            fc = getattr(part, "function_call", None)
            if fc is not None:
                calls.append({"function": {"name": fc.name, "arguments": dict(fc.args or {})}})
                continue
            if getattr(part, "text", None) and not getattr(part, "thought", False):
                texts.append(part.text)
        if texts or calls:
            msg: dict[str, Any] = {
                "role": "assistant" if role == "model" else "user",
                "content": "\n".join(texts),
            }
            if calls:
                msg["tool_calls"] = calls
            messages.append(msg)

    body: dict[str, Any] = {"messages": messages}
    if tools:
        body["tools"] = tools
    options: dict[str, Any] = {}
    temperature = getattr(config, "temperature", None)
    if temperature is not None:
        options["temperature"] = temperature
    body["options"] = options
    if getattr(config, "response_mime_type", None) == "application/json":
        body["format"] = "json"
    return body


# ------------------------------------------------------------------ yanit cevirisi
def from_ollama(data: dict[str, Any]) -> types.GenerateContentResponse:
    message = data.get("message") or {}
    parts: list[types.Part] = []
    text = (message.get("content") or "").strip()
    if text:
        parts.append(types.Part(text=text))
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        parts.append(types.Part(function_call=types.FunctionCall(name=fn.get("name"), args=args)))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(
            content=types.Content(role="model", parts=parts),
            finish_reason=types.FinishReason.STOP,
        )],
        model_version=model_label(data.get("model") or ""),
    )


# ------------------------------------------------------------------ istemci
class LocalLLM:
    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:11434",
        models: list[str] | None = None,
        num_ctx: int = 8192,
        timeout: float = 120.0,
        keep_alive: str = "10m",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.models = [m for m in (models or ["qwen2.5:7b"]) if m]
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._transport = transport
        self._up_at = 0.0
        self._up: bool = False
        self._warned_down = False

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url, timeout=timeout, transport=self._transport)

    async def is_up(self) -> bool:
        """Servis ayakta mi (30 sn onbellekli; kapaliysa oturumda bir kez uyarir)."""
        now = time.monotonic()
        if self._up_at and now - self._up_at < _HEALTH_TTL_S:
            return self._up
        try:
            async with self._client(1.5) as client:
                self._up = (await client.get("/api/tags")).status_code == 200
        except httpx.HTTPError:
            self._up = False
        self._up_at = now
        if not self._up and not self._warned_down:
            self._warned_down = True
            logger.warning(f"Yerel model servisi (Ollama) erisilemiyor: {self.url}")
        elif self._up:
            self._warned_down = False
        return self._up

    async def warm_up(self) -> bool:
        """Ana modeli bellege onceden yukler (ilk yanit ~15 sn yerine birkac sn surer)."""
        try:
            async with self._client(self.timeout) as client:
                # num_ctx generate() ile AYNI olmali; farkliysa Ollama modeli yeniden yukler
                resp = await client.post("/api/generate", json={
                    "model": self.models[0], "keep_alive": self.keep_alive,
                    "options": {"num_ctx": self.num_ctx},
                })
        except httpx.HTTPError as exc:
            logger.debug(f"Yerel model on-yukleme basarisiz: {exc!r}")
            return False
        if resp.status_code == 200:
            logger.info(f"Yerel model bellege yuklendi: {self.models[0]}")
        return resp.status_code == 200

    async def generate(
        self, contents: Any, config: types.GenerateContentConfig | None = None
    ) -> tuple[types.GenerateContentResponse, str]:
        """(yanit, kullanilan model). Modeller sirayla denenir; hepsi duserse LocalLLMError."""
        body = to_ollama(contents, config)
        body["options"]["num_ctx"] = self.num_ctx
        body.update(stream=False, keep_alive=self.keep_alive)
        errors: list[str] = []
        async with self._client(self.timeout) as client:
            for model in self.models:
                try:
                    resp = await client.post("/api/chat", json={**body, "model": model})
                except httpx.HTTPError as exc:  # zaman asimi / baglanti
                    errors.append(f"{model}: {type(exc).__name__}")
                    continue
                if resp.status_code != 200:
                    errors.append(f"{model}: HTTP {resp.status_code} {resp.text[:120]}")
                    continue
                result = from_ollama(resp.json())
                if not (result.candidates and result.candidates[0].content.parts):
                    errors.append(f"{model}: bos yanit")
                    continue
                return result, model
        raise LocalLLMError("Yerel model yanit vermedi: " + "; ".join(errors))


_UNSET = object()
_configured: Any = _UNSET


def configure(settings: Any) -> LocalLLM | None:
    """Istemciyi verilen ayarlardan kur (orn. sunucunun zorlanmis ayar kopyasi)."""
    global _configured
    _configured = _build(settings)
    return _configured


def get_local_llm() -> LocalLLM | None:
    """Surec genelinde tek, paylasilan istemci; yerel yedek kapaliysa None."""
    if _configured is not _UNSET:
        return _configured
    return _from_global_settings()


@lru_cache(maxsize=1)
def _from_global_settings() -> LocalLLM | None:
    from config.settings import get_settings

    return _build(get_settings())


def _build(s: Any) -> LocalLLM | None:
    if not s.local_llm_enabled:
        return None
    return LocalLLM(
        url=s.local_llm_url,
        models=[s.local_llm_model, s.local_llm_small_model],
        num_ctx=s.local_llm_num_ctx,
        timeout=s.local_llm_timeout,
        keep_alive=s.local_llm_keep_alive,
    )
