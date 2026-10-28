"""Tek bir uzman ajan - elle yurutulen arac dongusu (her cagride retry + timeout)."""

from __future__ import annotations

import asyncio
import inspect
import types as types_mod
import typing
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from loguru import logger

from agents.agent_tools import build_callables
from agents.genai_util import _announce_fallback, generate_with_retry
from agents.schemas import AgentResult, AgentSpec


import json as _json
import re as _re


def _json_snippet(obj: dict | None, limit: int = 6000) -> str:
    if not obj:
        return "{}"
    text = _json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    return text if len(text) <= limit else text[:limit] + "\n... (kirpildi)"


def _extract_path(task: str) -> str:
    """Gorev metninden dosya/dizin yolu benzeri bir belirtec ayiklar."""
    m = _re.search(r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+|[\w.\-/\\]+\.(?:md|markdown|py|txt|json))", task)
    if m:
        return m.group(1)
    for token in ("prompts", "agents", "core", "tools", "ui", "bridge", "."):
        if token in task.lower():
            return token
    return ""


def is_openrouter_model(model: str | None) -> bool:
    """OpenRouter kimlikleri "saglayici/model" bicimindedir (orn. "qwen/qwen3-8b:free").

    Gemini kimlikleri ya duz ("gemini-flash-lite-latest") ya da "models/..." onekli olur.
    """
    return bool(model) and "/" in model and not model.startswith(("models/", "tunedModels/"))


def is_claude_model(model: str | None) -> bool:
    """Dogrudan Anthropic API'ye giden Claude kimlikleri (orn. "claude-opus-5-5").

    OpenRouter uzerindeki "anthropic/claude-..." kimlikleri bu kapsama girmez.
    """
    return bool(model) and model.startswith("claude-")


_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}


def _openai_tool_schema(fn: Any) -> dict[str, Any]:
    """Callable imzasi + docstring'den OpenAI/OpenRouter `tools` semasi uretir."""
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in inspect.signature(fn).parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        hint = hints.get(pname, str)
        base = typing.get_origin(hint) or hint
        if base in (typing.Union, types_mod.UnionType):  # orn. str | None -> str
            base = next((a for a in typing.get_args(hint) if a is not type(None)), str)
            base = typing.get_origin(base) or base
        prop: dict[str, Any] = {"type": _JSON_TYPES.get(base, "string")}
        if prop["type"] == "array":
            prop["items"] = {"type": "string"}
        props[pname] = prop
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": " ".join((inspect.getdoc(fn) or fn.__name__).split())[:1000],
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def _short_error(exc: BaseException) -> str:
    text = str(exc)
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return "API kotasi doldu (429). Gecerli bir GEMINI_API_KEY / kota gerekiyor."
    if any(t in text for t in ("503", "504", "UNAVAILABLE", "DEADLINE")) or isinstance(
        exc, asyncio.TimeoutError
    ):
        return "Model su an asiri yogun (5xx / zaman asimi). Biraz sonra tekrar deneyin."
    return f"{type(exc).__name__}: {text[:160]}"


class Agent:
    def __init__(
        self,
        spec: AgentSpec,
        client: genai.Client,
        *,
        default_models: list[str],
        default_max_steps: int,
        inbox_path: Path | None = None,
        openrouter: Any | None = None,
        claude: Any | None = None,
    ) -> None:
        self.spec = spec
        self.client = client
        self.openrouter = openrouter
        self.claude = claude
        declared = list(dict.fromkeys(
            m for m in (spec.model, spec.fallback_model, *spec.fallback_models) if m
        ))
        # Claude zinciri (agents.json'daki "claude-*" tanimlari) - varsa ilk denenir
        self.claude_models: list[str] = [m for m in declared if is_claude_model(m)]
        # OpenRouter zinciri (agents.json'daki "saglayici/model" tanimlari)
        self.openrouter_models: list[str] = [m for m in declared if is_openrouter_model(m)]
        # Gemini zinciri: ajana ozel Gemini modeli yoksa global zincir (en son yedek)
        self.models: list[str] = [
            m for m in declared if not (is_openrouter_model(m) or is_claude_model(m))
        ] or list(default_models)
        self.max_steps = spec.max_steps or default_max_steps
        self._callables = build_callables(spec.capabilities, inbox_path=inbox_path)
        self._by_name = {fn.__name__: fn for fn in self._callables}

    async def run(self, task: str, context: str = "") -> AgentResult:
        artifact: dict | None = None
        skill_note = ""
        if self.spec.skill:
            artifact = await self._run_skill(task)
            skill_note = (
                "\n\n[YETENEK CIKTISI - asagidaki JSON raporu ozetle]\n"
                + _json_snippet(artifact)
            )

        user_text = task if not context else f"[BAGLAM]\n{context}\n\n[GOREV]\n{task}"
        user_text += skill_note

        primary = (self.claude_models or self.openrouter_models or self.models)[0]
        # hangi modelin kullanildigi + yedege dusulup dusulmedigi (adimlar boyunca birikir)
        meta: dict[str, Any] = {"model": None, "fallback": False, "primary": primary}

        # Cevrimdisi: Claude/OpenRouter'i bosuna deneme; Gemini yolu yerel modele duser
        from agents.genai_util import _get_local, _is_online

        offline = _get_local() is not None and not await _is_online()

        if self.claude_models and not offline:
            result = await self._run_claude(user_text, artifact)
            if result is not None:
                return result
            # Claude basarisiz -> OpenRouter (yoksa Gemini) zincirine ACIK gecis
            _announce_fallback(
                self.claude_models[-1], (self.openrouter_models or self.models)[0],
                "Claude basarisiz / anahtar yok", None,
            )
            meta["fallback"] = True

        if self.openrouter_models and not offline:
            result = await self._run_openrouter(user_text, artifact)
            if result is not None:
                if meta["fallback"]:
                    result.fallback = True
                    result.primary_model = primary
                return result
            # OpenRouter zinciri tamamen basarisiz -> Gemini zincirine ACIK gecis
            _announce_fallback(
                self.openrouter_models[-1], self.models[0],
                "OpenRouter zinciri basarisiz / anahtar yok", None,
            )
            meta["fallback"] = True

        contents: list[Any] = [
            types.Content(role="user", parts=[types.Part(text=user_text)])
        ]
        config = self._build_config()
        used: list[str] = []

        for _ in range(self.max_steps + 1):
            info: dict[str, Any] = {}
            try:
                response = await generate_with_retry(
                    self.client, model=self.models, contents=contents, config=config, info=info
                )
            except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
                logger.warning(f"[{self.spec.name}] uretim hatasi: {exc!r}")
                error = _short_error(exc)
                if info.get("local_error"):
                    error += " Yerel model (Ollama) de yanit vermedi."
                return AgentResult(
                    ok=False, text="", error=error, steps=len(used), tool_calls=used,
                    model=meta["model"], fallback=meta["fallback"], primary_model=meta["primary"],
                )
            meta["model"] = info.get("model")
            meta["fallback"] = meta["fallback"] or bool(info.get("fallback"))

            candidate = (getattr(response, "candidates", None) or [None])[0]
            content = getattr(candidate, "content", None)
            parts = list(getattr(content, "parts", None) or [])
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

            if not calls:
                text = (getattr(response, "text", None) or "").strip() or "(ajan bos yanit dondurdu)"
                return AgentResult(
                    ok=True, text=text, steps=len(used), tool_calls=used, artifact=artifact,
                    model=meta["model"], fallback=meta["fallback"], primary_model=meta["primary"],
                )

            contents.append(content)
            tool_parts = []
            for call in calls:
                used.append(call.name)
                result = await self._invoke(call.name, dict(call.args or {}))
                tool_parts.append(
                    types.Part.from_function_response(name=call.name, response={"result": result})
                )
            contents.append(types.Content(role="user", parts=tool_parts))

        return AgentResult(
            ok=True, text="(adim siniri asildi, gorev tamamlanamamis olabilir)",
            steps=len(used), tool_calls=used, artifact=artifact,
            model=meta["model"], fallback=meta["fallback"], primary_model=meta["primary"],
        )

    async def _run_skill(self, task: str) -> dict:
        from agents.skills import get_skill

        fn = get_skill(self.spec.skill or "")
        if fn is None:
            return {"error": f"bilinmeyen yetenek: {self.spec.skill}"}
        target = _extract_path(task)
        try:
            return await asyncio.to_thread(lambda: fn(target=target))
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"[{self.spec.name}] yetenek hatasi")
            return {"error": f"{type(exc).__name__}: {exc}"}

    async def _run_claude(self, user_text: str, artifact: dict | None) -> AgentResult | None:
        """Claude uzerinden elle arac dongusuyle calisir; basarisiz/reddederse None.

        None donerse cagiran taraf OpenRouter -> Gemini zincirine gecer.
        """
        if self.claude is None or not getattr(self.claude, "available", False):
            logger.warning(
                f"[{self.spec.name}] Claude kullanilamiyor (ANTHROPIC_API_KEY yok?), "
                f"OpenRouter zincirine geciliyor"
            )
            return None
        tools = [
            {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
            for s in (_openai_tool_schema(fn)["function"] for fn in self._callables)
        ] or None

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
        used: list[str] = []
        for model in self.claude_models:
            for _ in range(self.max_steps + 1):
                try:
                    response = await self.claude.create(
                        messages, model=model, system=self.spec.system_prompt,
                        tools=tools, effort=self.spec.effort,
                    )
                except Exception as exc:  # noqa: BLE001 - bakiye yok / 401 / 429 / ag hatasi
                    logger.warning(f"[{self.spec.name}] Claude hatasi ({model}): {exc!r}")
                    break
                if response.stop_reason == "refusal":
                    logger.warning(f"[{self.spec.name}] Claude istegi reddetti ({model})")
                    break

                if response.stop_reason != "tool_use":
                    text = "".join(
                        b.text for b in response.content if b.type == "text"
                    ).strip() or "(ajan bos yanit dondurdu)"
                    return AgentResult(
                        ok=True, text=text, steps=len(used), tool_calls=used, artifact=artifact,
                        model=response.model, fallback=model != self.claude_models[0],
                        primary_model=self.claude_models[0],
                    )

                # yanit (thinking bloklari dahil) degistirilmeden geri eklenir
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    used.append(block.name)
                    result = await self._invoke(block.name, dict(block.input or {}))
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": _json.dumps(result, ensure_ascii=False, default=str)[:8000],
                    })
                messages.append({"role": "user", "content": results})
            else:
                return AgentResult(
                    ok=True, text="(adim siniri asildi, gorev tamamlanamamis olabilir)",
                    steps=len(used), tool_calls=used, artifact=artifact,
                    model=model, fallback=model != self.claude_models[0],
                    primary_model=self.claude_models[0],
                )
            # bu model basarisiz -> varsa siradaki Claude modeli bastan baslar
            messages = [{"role": "user", "content": user_text}]
        return None

    async def _run_openrouter(self, user_text: str, artifact: dict | None) -> AgentResult | None:
        """OpenRouter uzerinden (yetenek varsa OpenAI tools dongusuyle) calisir; basarisizsa None.

        Araclu bir ajanda zincir arac cagirmayi desteklemezse None doner -> Gemini zinciri
        (function calling destekli) devralir; aracsiz OpenRouter'a dusmek isi yapamaz.
        """
        if self.openrouter is None or not getattr(self.openrouter, "available", False):
            logger.warning(
                f"[{self.spec.name}] OpenRouter kullanilamiyor (OPENROUTER_API_KEY yok?), "
                f"Gemini zincirine geciliyor"
            )
            return None
        if self.spec.grounded_search:
            logger.debug(f"[{self.spec.name}] OpenRouter yolunda grounded search kullanilmaz")
        primary, *fallbacks = self.openrouter_models
        tools = [_openai_tool_schema(fn) for fn in self._callables] or None

        messages: list[dict[str, Any]] = []
        if self.spec.system_prompt:
            messages.append({"role": "system", "content": self.spec.system_prompt})
        messages.append({"role": "user", "content": user_text})

        used: list[str] = []
        fell_back = False
        model_used: str | None = None
        for _ in range(self.max_steps + 1):
            info: dict[str, Any] = {}
            try:
                message = await self.openrouter.chat(
                    messages, model=primary, fallback_models=fallbacks, info=info,
                    temperature=self.spec.temperature,
                    **({"tools": tools} if tools else {}),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[{self.spec.name}] OpenRouter hatasi: {exc!r}")
                return None
            model_used = info.get("model", primary)
            fell_back = fell_back or bool(info.get("fallback"))

            calls = list(getattr(message, "tool_calls", None) or []) if tools else []
            if not calls:
                text = (message.content or "").strip() or "(ajan bos yanit dondurdu)"
                return AgentResult(
                    ok=True, text=text, steps=len(used), tool_calls=used, artifact=artifact,
                    model=model_used, fallback=fell_back, primary_model=primary,
                )

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                    for c in calls
                ],
            })
            for call in calls:
                name = call.function.name
                try:
                    args = _json.loads(call.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguman nesne degil")
                except ValueError as exc:
                    result: Any = {"error": f"gecersiz JSON arguman: {exc}"}
                else:
                    result = await self._invoke(name, args)
                used.append(name)
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": _json.dumps(result, ensure_ascii=False, default=str)[:8000],
                })

        return AgentResult(
            ok=True, text="(adim siniri asildi, gorev tamamlanamamis olabilir)",
            steps=len(used), tool_calls=used, artifact=artifact,
            model=model_used, fallback=fell_back, primary_model=primary,
        )

    # ------------------------------------------------------------- internal
    def _build_config(self) -> types.GenerateContentConfig:
        base: dict[str, Any] = dict(
            system_instruction=self.spec.system_prompt,
            temperature=self.spec.temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        tools = self._tools()
        if tools:
            base["tools"] = tools
        return types.GenerateContentConfig(**base)

    def _tools(self) -> list[types.Tool] | None:
        if self.spec.grounded_search:
            tool = self._google_search_tool()
            return [tool] if tool is not None else None
        if not self._callables:
            return None
        api = getattr(self.client, "_api_client", None)
        declarations: list[types.FunctionDeclaration] = []
        for fn in self._callables:
            try:
                declarations.append(
                    types.FunctionDeclaration.from_callable(client=api, callable=fn)
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Arac semasi cikarilamadi ({fn.__name__}): {exc}")
        return [types.Tool(function_declarations=declarations)] if declarations else None

    async def _invoke(self, name: str, args: dict[str, Any]) -> Any:
        fn = self._by_name.get(name)
        if fn is None:
            return {"error": f"bilinmeyen arac: {name}"}
        try:
            return await asyncio.to_thread(lambda: fn(**args))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[{self.spec.name}] arac hatasi {name}: {exc!r}")
            return {"error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _google_search_tool() -> types.Tool | None:
        for factory in (
            lambda: types.Tool(google_search=types.GoogleSearch()),
            lambda: types.Tool(google_search_retrieval=types.GoogleSearchRetrieval()),
        ):
            try:
                return factory()
            except Exception:  # noqa: BLE001
                continue
        return None
