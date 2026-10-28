"""Ajan orkestratoru - JARVIS (Conductor) kisisel asistan departmanlarina delege eder.

bridge/inbox.txt  <- gorev istekleri (JSON satirlari)
bridge/outbox.txt -> ajan sonuclari (sesli beyin bunlari okuyup asistana enjekte eder)

Akis:  istek -> (auto ise) Conductor departman+alt-ajan secer -> otonomi kapisi ->
        Agent (skill + LLM) calisir -> Supabase log + ntfy bildirim -> outbox.
"""

from __future__ import annotations

import asyncio
import json
import time
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
from agents.schemas import AUTONOMY_BADGE, Autonomy, TaskRequest, TaskUpdate, parse_department
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
        self.router = self._make_router()
        from agents.qa import VeronicaQA

        qa_cfg = self.router.registry.qa if self.router is not None else {}
        self.qa = VeronicaQA(claude=self.claude, openrouter=self.openrouter, genai_client=self.client,
                             max_result_chars=int(qa_cfg.get("max_result_chars", 6000)))

    def _start_dashboard(self) -> None:
        """Decision Pipeline panosu (ui/dashboard, FastAPI). Hata orkestratoru durdurmaz."""
        if not getattr(self.settings, "dashboard_enabled", False):
            return
        try:
            from ui.dashboard.server import start_dashboard

            start_dashboard(self.settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[pano] Decision Pipeline baslatilamadi: {exc!r}")

    def _make_router(self) -> Any | None:
        """Model router (router/). Kapaliysa ya da kurulamazsa None -> eski davranis
        (Conductor LLM + agents.json modelleri). Kurulamamasi ACIKCA loglanir."""
        if not self.settings.router_enabled:
            logger.info("[router] KAPALI (JARVIS_ROUTER_ENABLED=false) - eski yonlendirme kullaniliyor.")
            return None
        try:
            import router as router_pkg

            built = router_pkg.build_router(self.settings, agents=self.agents, llm_ask=self._llm_ask)
            router_pkg.set_active(built)
            return built
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[router] KURULAMADI, eski yonlendirmeye donuluyor: {exc!r}")
            return None

    async def _llm_ask(self, prompt: str) -> str:
        """Router'in dusuk guvende sordugu tek JSON sorusu: en hizli Gemini modelleri."""
        from agents.genai_util import generate_with_retry

        registry = self.router.registry if self.router is not None else None
        models = [m for m in registry.llm_models if registry.is_active(m)] if registry else []
        resp = await generate_with_retry(
            self.client, model=models or self.settings.agent_model_chain[:1], contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json"),
            attempts=1,
        )
        return getattr(resp, "text", "") or ""

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
        self._start_dashboard()
        if self.router is not None:
            from router import warm_up

            logger.info("[router] AKTIF - yerel siniflandirici ve model denetimi arka planda hazirlaniyor.")
            warm = asyncio.create_task(warm_up(self.router, self.settings))
            self._running.add(warm)
            warm.add_done_callback(self._running.discard)
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
            started = time.perf_counter()
            name = (request.agent or "auto").strip().lower()
            reason = ""
            route = None
            if self.router is not None:
                route = await self._route(request, name)
                name, reason = route.agent or name, route.reason
            elif name in ("", "auto") or name not in self.agents:
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
                self._record_unrun(request, route, spec, "blocked", started)
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
                    self._record_unrun(request, route, spec, "cancelled", started)
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
                model_chain=route.chain if route is not None else None,
            )
            result = await agent.run(request.task, request.context)
            qa_note = ""
            if route is not None and result.ok and self._qa_due(route):
                result, qa_note = await self._run_qa(request, spec, agent, result)

            # Yedek modele dusulduyse cevaba ACIK isaret koy (sessiz fallback yok)
            mark = ""
            if result.fallback:
                mark = (f"[YEDEK MODEL: {result.model} kullanildi - asil model "
                        f"{result.primary_model} yanit vermedi] ")
                logger.bind(event="agent_fallback", agent=spec.name, model=result.model).warning(
                    f"[gorev {request.id}] {spec.name} YEDEK modelle calisti: {result.model}"
                )

            if route is not None:
                self.router.record_done(
                    request.id, ok=result.ok, error=result.error, agent=spec.name,
                    model_used=result.model, primary_model=result.primary_model or route.model_id,
                    fallback=result.fallback, chain=route.chain, status="done" if result.ok else "failed",
                    total_ms=round((time.perf_counter() - started) * 1000, 1), qa=qa_note or None,
                    est_cost_usd=self.router.registry.estimate_cost(
                        result.model, request_chars=len(request.task) + len(request.context or ""),
                        calls=result.steps + 1),
                )
            mark = mark + qa_note
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

    # ------------------------------------------------------------------ router
    async def _route(self, request: TaskRequest, name: str) -> Any:
        """Ajan + model karari (router). Ajan adi verildiyse yalnizca model secilir;
        departman adi verildiyse ("okul", "SISTEM") ajan o departmandan secilir. Yerel ajan
        guveni esigin altindaysa Conductor LLM'ine sorulur. Router yalnizca KIMLIK dondurur:
        otonomi/onay kapisi bu karardan sonra aynen uygulanir."""
        from router import RouteRequest

        explicit = name in self.agents
        dept = None if explicit or name in ("", "auto") else parse_department(name)
        candidates = {n for n, s in self.agents.items() if s.department == dept} if dept else None
        candidates = candidates or None
        if not explicit:
            self._emit(request, "routing", "JARVIS ajan ve model seciyor")
        hint = self.agents[name].model if explicit else None
        decision = await self.router.route(RouteRequest(
            text=request.task, context=request.context, request_id=request.id, hint_model=hint,
            pick_agent=not explicit, agent_name=name if explicit else None,
            agent_candidates=candidates, needs_tools=True,
        ))
        if explicit:
            decision.agent, decision.agent_source, decision.agent_confidence = name, "explicit", 1.0
        else:
            agent, source, confidence = decision.agent, "classifier", decision.agent_confidence
            if agent is None or (confidence or 0.0) < self.router.registry.agent_threshold:
                llm = await self.conductor.route(request.task, request.context)
                failed = llm.reason.startswith("[YEDEK YONLENDIRME")
                if failed and agent is not None:
                    decision.warnings.append(
                        f"Conductor LLM yanit vermedi; dusuk guvenli yerel ajan karari kullanildi ({agent})")
                    logger.bind(event="routing_warning").warning(
                        f"[router {request.id}] {decision.warnings[-1]}")
                elif llm.agent in self.agents and (candidates is None or llm.agent in candidates):
                    agent, source, confidence = llm.agent, "conductor_llm", llm.confidence
                    decision.reason = f"{decision.reason}; ajan: Conductor LLM ({llm.reason})"
                elif agent is None:
                    agent, source, confidence = llm.agent, "conductor_llm", llm.confidence
            if agent not in self.agents:
                agent = next(iter(sorted(candidates))) if candidates else next(iter(self.agents))
                decision.warnings.append(f"ajan secilemedi -> {agent}")
                logger.bind(event="routing_warning").warning(f"[router {request.id}] {decision.warnings[-1]}")
            decision = self.router.reroute_for_agent(
                decision, agent=agent, hint=self.agents[agent].model, needs_tools=True,
                source=source, confidence=confidence,
            )
        self.router.record(decision, request.task)
        return decision

    def _record_unrun(self, request: TaskRequest, route: Any, spec: Any, status: str, started: float) -> None:
        """Calistirilmayan gorev (onay yok / insan odakli) de kayda ve canli panoya yazilir."""
        if route is None or self.router is None:
            return
        self.router.record_done(
            request.id, ok=False, status=status, agent=spec.name, model_used=None,
            primary_model=route.model_id, fallback=False, chain=route.chain, est_cost_usd=0.0,
            total_ms=round((time.perf_counter() - started) * 1000, 1),
            error="onay verilmedi" if status == "cancelled" else "insan odakli ajan",
        )

    def _qa_due(self, route: Any) -> bool:
        cfg = self.router.registry.qa if self.router is not None else {}
        if not cfg.get("enabled", False):
            return False
        order = ("basit", "orta", "zor")
        need = str(cfg.get("min_difficulty", "zor"))
        if route.difficulty not in order or need not in order:
            return False
        return order.index(route.difficulty) >= order.index(need)

    async def _run_qa(self, request: TaskRequest, spec: Any, agent: Any, result: Any) -> tuple[Any, str]:
        """V.E.R.O.N.I.C.A. QA: onay yoksa ajan geri bildirimle en fazla max_retries kez
        yeniden calisir. Donus: (son sonuc, cevaba eklenecek QA notu)."""
        from router import RouteRequest

        cfg = self.router.registry.qa
        qa_route = await self.router.route(RouteRequest(
            text=request.task, request_id=f"{request.id}-qa", forced_task_type="qa"))
        self.router.record(qa_route, request.task)
        dept = spec.department.value if spec.department else ""
        self._emit(request, "running", "V.E.R.O.N.I.C.A. kalite kontrolu yapiyor",
                   agent=spec.name, department=dept, autonomy=spec.autonomy.value)
        verdict = await self.qa.review(request.task, result.text, qa_route.chain, request_id=request.id)
        retries = 0
        while verdict.approved is False and retries < int(cfg.get("max_retries", 1)):
            retries += 1
            feedback = "\n".join(f"- {i}" for i in verdict.issues) or verdict.summary or "kaliteyi artir"
            context = ((request.context + "\n\n") if request.context else "") + (
                "[V.E.R.O.N.I.C.A. QA GERI BILDIRIMI - bu sorunlari duzelterek gorevi yeniden yap]\n"
                f"{feedback}\n\n[ONCEKI SONUC]\n{result.text[:3000]}")
            self._emit(request, "running", f"QA geri bildirimiyle yeniden calisiyor ({retries})",
                       agent=spec.name, department=dept, autonomy=spec.autonomy.value)
            retry = await agent.run(request.task, context)
            if not retry.ok:
                break
            result = retry
            verdict = await self.qa.review(request.task, result.text, qa_route.chain, request_id=request.id)

        self.router.log.write("qa", {
            "request_id": request.id, "approved": verdict.approved, "issues": verdict.issues,
            "model": verdict.model, "fallback": verdict.fallback, "retries": retries,
            "errors": verdict.errors,
            "est_cost_usd": self.router.registry.estimate_cost(
                verdict.model, request_chars=len(request.task) + min(len(result.text), 6000),
                calls=retries + 1),
        })
        backup = f" (yedek model {verdict.model})" if verdict.fallback else ""
        if verdict.approved is True:
            return result, f"[QA onayli{backup}] "
        if verdict.approved is False:
            issues = "; ".join(verdict.issues[:3]) or verdict.summary
            return result, f"[QA ONAYLANMADI{backup}: {issues}] "
        logger.bind(event="qa_fallback").warning(f"[QA {request.id}] YAPILAMADI: {verdict.errors}")
        return result, "[QA YAPILAMADI: denetim modelleri yanit vermedi] "

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
