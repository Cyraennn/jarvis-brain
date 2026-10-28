"""Ajan orkestratoru - JARVIS (Conductor) kisisel asistan departmanlarina delege eder.

bridge/inbox.txt  <- gorev istekleri (JSON satirlari)
bridge/outbox.txt -> ajan sonuclari (sesli beyin bunlari okuyup asistana enjekte eder)

Akis:  istek -> (auto ise) Conductor departman+alt-ajan secer -> otonomi kapisi ->
        Agent (skill + LLM) calisir -> Supabase log + ntfy bildirim -> outbox.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google import genai
from google.genai import types
from loguru import logger

from agents.agent import Agent, is_claude_model, is_openrouter_model
from agents.conductor import Conductor
from agents.events import OrchestratorObserver
from agents.integrations import SupabaseSync
from agents.integrations.notifier import Notifier
from agents.registry import load_agents, load_orchestrator_config
from agents.schemas import AUTONOMY_BADGE, Autonomy, TaskRequest, TaskUpdate
from config.settings import Settings
from core.bridge_listener import BridgeListener


class AgentOrchestrator:
    def __init__(self, settings: Settings, observer: OrchestratorObserver | None = None) -> None:
        self.settings = settings
        self.observer = observer or OrchestratorObserver()
        self.agents = load_agents(settings.agent_config_path)
        orchestrator_cfg = load_orchestrator_config(settings.agent_config_path)

        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                api_version=settings.agents_api_version, timeout=120_000
            ),
        )
        self.openrouter = self._make_openrouter(settings.openrouter_api_key)
        self.claude = self._make_claude(settings.anthropic_api_key, settings.anthropic_workspace_id)
        conductor_models = [
            m for m in (orchestrator_cfg.get("default_model"), *orchestrator_cfg.get("fallback_models", []))
            if m and is_openrouter_model(m)
        ]
        self.conductor = Conductor(
            self.client, settings.agent_model_chain,
            agents=self.agents, openrouter=self.openrouter, openrouter_models=conductor_models,
        )
        self.supabase = SupabaseSync(
            settings.supabase_url, settings.supabase_key, settings.supabase_table
        )
        self.notifier = Notifier(settings.ntfy_topic, settings.ntfy_server)

        self._inbox = BridgeListener(settings.agent_inbox_path, poll_interval=0.4)
        self._sem = asyncio.Semaphore(max(1, settings.agents_max_concurrent))
        self._shutdown = asyncio.Event()
        self._running: set[asyncio.Task[Any]] = set()

    @staticmethod
    def _make_openrouter(api_key: str) -> Any | None:
        """OpenRouter istemcisi; `openai` paketi yoksa None (ajanlar Gemini'de kalir)."""
        try:
            from core.openrouter_client import OpenRouterClient
        except ImportError as exc:
            logger.warning(f"OpenRouter devre disi ('openai' paketi yok?): {exc}")
            return None
        return OpenRouterClient(api_key or None)

    @staticmethod
    def _make_claude(api_key: str, workspace_id: str) -> Any | None:
        """Claude istemcisi; `anthropic` paketi yoksa None (ajanlar OpenRouter'da kalir)."""
        try:
            from core.claude_client import ClaudeClient
        except ImportError as exc:
            logger.warning(f"Claude devre disi ('anthropic' paketi yok?): {exc}")
            return None
        return ClaudeClient(api_key or None, workspace_id or None)

    # ------------------------------------------------------------------ lifecycle
    def request_shutdown(self) -> None:
        self._shutdown.set()

    async def run(self) -> None:
        from agents.departments import AGENT_COUNT

        logger.success(
            f"Ajan orkestratoru aktif - {len(self.agents)} ajan / {AGENT_COUNT} yetenek, "
            f"6 departman (model {self.settings.agents_model})"
        )
        openrouter_agents = [s.name for s in self.agents.values()
                             if is_openrouter_model(s.model) or is_openrouter_model(s.fallback_model)]
        if openrouter_agents:
            state = "aktif" if getattr(self.openrouter, "available", False) else "ANAHTAR YOK -> Gemini"
            logger.info(f"OpenRouter ({state}): {', '.join(openrouter_agents)} "
                        f"| conductor: {self.conductor.openrouter_models or 'Gemini'}")
        claude_agents = [s.name for s in self.agents.values()
                         if is_claude_model(s.model) or is_claude_model(s.fallback_model)]
        if claude_agents:
            state = "aktif" if getattr(self.claude, "available", False) else "ANAHTAR YOK -> OpenRouter"
            logger.info(f"Claude ({state}): {', '.join(claude_agents)}")
        try:
            self.observer.on_agents_loaded(list(self.agents.values()))
        except Exception:  # noqa: BLE001
            logger.exception("observer.on_agents_loaded")

        async for line in self._inbox.messages(stop=self._shutdown):
            request = self._parse(line)
            if request is None:
                continue
            self._emit(request, "queued", "kuyruga alindi")
            task = asyncio.create_task(self._handle(request))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
        logger.info("Orkestrator durdu.")

    # ------------------------------------------------------------------ handling
    def _parse(self, line: str) -> TaskRequest | None:
        try:
            data = json.loads(line)
            if isinstance(data, dict) and data.get("task"):
                return TaskRequest(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(f"Gecersiz gorev satiri atlandi: {line[:120]!r} ({exc})")
        return None

    async def _handle(self, request: TaskRequest) -> None:
        async with self._sem:
            name = (request.agent or "auto").strip().lower()
            reason = ""
            if name in ("", "auto") or name not in self.agents:
                self._emit(request, "routing", "JARVIS departman seciyor")
                decision = await self.conductor.route(request.task, request.context)
                name = decision.agent
                reason = decision.reason
                dep = decision.department.value if decision.department else "?"
                logger.info(f"[gorev {request.id}] Conductor -> {dep}/{name}  ({reason})")

            spec = self.agents.get(name) or next(iter(self.agents.values()))
            dept = spec.department.value if spec.department else ""
            badge = AUTONOMY_BADGE.get(spec.autonomy, spec.autonomy.value)

            # --- otonomi kapisi ---
            if spec.autonomy == Autonomy.HUMAN_LED:
                self._emit(request, "blocked", "yalnizca insan baslatir",
                           agent=spec.name, department=dept, autonomy=spec.autonomy.value)
                await self.notifier.notify(
                    f"JARVIS · {spec.title}",
                    f"'{request.task[:80]}' gorevi bu ajanla YALNIZCA insan tarafindan baslatilir.",
                    priority=4, tags=["warning", "lock"],
                )
                self._write_outbox(
                    f"[{spec.title}] Bu ajan Insan Odakli. Gorevi manuel baslatman gerekiyor: "
                    f"{request.task[:120]}"
                )
                return

            # Zamanli gorevler (source "zamanli...") kullanici tarafindan kurulurken onaylandi;
            # vaktinde kullanici basinda olmayabilir -> onay penceresi beklenmez.
            scheduled = (request.source or "").startswith("zamanli")
            if (spec.autonomy == Autonomy.HUMAN_ASSISTED and self.settings.agents_require_approval
                    and not scheduled):
                self._emit(request, "awaiting_approval", f"onay bekliyor ({badge})",
                           agent=spec.name, department=dept, autonomy=spec.autonomy.value)
                await self.notifier.notify(
                    f"JARVIS · {spec.title} onay bekliyor",
                    f"{reason or request.task[:80]}",
                    priority=4, tags=["hourglass_flowing_sand"],
                )
                approved = await self._request_approval(request, spec, reason)
                if not approved:
                    self._emit(request, "cancelled", "onay verilmedi",
                               agent=spec.name, department=dept, autonomy=spec.autonomy.value)
                    self._write_outbox(f"[{spec.title}] Gorev onaylanmadi, calistirilmadi.")
                    return

            # --- calistir ---
            self._emit(request, "running", f"{spec.title} calisiyor ({badge})",
                       agent=spec.name, department=dept, autonomy=spec.autonomy.value)

            agent = Agent(
                spec, self.client,
                default_models=self.settings.agent_model_chain,
                default_max_steps=self.settings.agent_max_steps,
                inbox_path=self.settings.agent_inbox_path,
                openrouter=self.openrouter,
                claude=self.claude,
            )
            result = await agent.run(request.task, request.context)

            # Yedek modele dusulduyse cevaba ACIK isaret koy (sessiz fallback yok)
            mark = ""
            if result.fallback:
                mark = (f"[YEDEK MODEL: {result.model} kullanildi - asil model "
                        f"{result.primary_model} yanit vermedi] ")
                logger.bind(event="agent_fallback", agent=spec.name, model=result.model).warning(
                    f"[gorev {request.id}] {spec.name} YEDEK modelle calisti: {result.model}"
                )

            if result.ok:
                self._emit(request, "done",
                           f"{result.steps} arac cagrisi · model {result.model or '?'}"
                           + (" (YEDEK)" if result.fallback else ""),
                           agent=spec.name, department=dept, autonomy=spec.autonomy.value,
                           steps=result.steps, result=mark + result.text)
                self._write_outbox(f"[{spec.title}] {mark}{result.text}")
                if request.source == "zamanli:not":
                    await self._save_result_note(request, spec.title, result.text)
                if spec.autonomy == Autonomy.FULLY_AUTONOMOUS:
                    await self.notifier.notify(
                        f"JARVIS · {spec.title} tamamladi",
                        result.text[:180], priority=3, tags=["white_check_mark"],
                    )
            else:
                self._emit(request, "failed", result.error or "bilinmeyen hata",
                           agent=spec.name, department=dept, autonomy=spec.autonomy.value)
                self._write_outbox(f"[{spec.title}] Gorev tamamlanamadi: {result.error or 'hata'}")
                await self.notifier.notify(
                    f"JARVIS · {spec.title} basarisiz", result.error or "hata",
                    priority=4, tags=["x"],
                )

    async def _save_result_note(self, request: TaskRequest, title: str, text: str) -> None:
        """Zamanli gorev sonucunu kalici notlara (data/notes.md + Obsidian Notlar/) yazar."""
        from tools.basic_tools import remember_note

        note = f"Zamanli gorev ({title}): {request.task}\n\n{text}"
        try:
            saved = await asyncio.to_thread(remember_note, note)
            logger.info(f"[gorev {request.id}] sonuc nota kaydedildi: {saved.get('obsidian', saved.get('status'))}")
        except Exception:  # noqa: BLE001 - not hatasi gorevi basarisiz saymaz
            logger.exception(f"[gorev {request.id}] sonuc nota kaydedilemedi")

    async def _request_approval(self, request: TaskRequest, spec: Any, reason: str) -> bool:
        prompt = (
            f"'{spec.title}' ({AUTONOMY_BADGE[spec.autonomy]}) su gorevi calistirsin mi?\n\n"
            f"{request.task}\n\nGerekce: {reason or '-'}"
        )
        confirm = getattr(self.observer, "confirm", None)
        if callable(confirm):
            try:
                return bool(await asyncio.to_thread(confirm, prompt))
            except Exception:  # noqa: BLE001
                logger.exception("Onay istegi basarisiz")
        # UI onayi bagli degil -> ayara gore otomatik
        return bool(self.settings.agents_auto_approve_assisted)

    # ------------------------------------------------------------------ io
    def _write_outbox(self, text: str) -> None:
        path = self.settings.agent_outbox_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(" ".join(text.split()).strip() + "\n")
        except OSError as exc:
            logger.error(f"outbox yazilamadi: {exc}")

    def _emit(
        self,
        request: TaskRequest,
        status: str,
        detail: str = "",
        *,
        agent: str | None = None,
        department: str = "",
        autonomy: str = "",
        steps: int = 0,
        result: str | None = None,
    ) -> None:
        update = TaskUpdate(
            id=request.id,
            agent=agent or request.agent,
            status=status,  # type: ignore[arg-type]
            department=department,
            autonomy=autonomy,
            detail=detail,
            steps=steps,
            result=result,
        )
        logger.info(f"[gorev {request.id}] {status} · {update.agent} · {detail}")
        try:
            self.observer.on_task(update)
        except Exception:  # noqa: BLE001
            logger.exception("observer.on_task")
        asyncio.create_task(self.supabase.log_task(update.model_dump()))
