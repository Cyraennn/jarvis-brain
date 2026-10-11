"""Proaktif zamanlayici kolu - APScheduler (AsyncIOScheduler) uzerinde tek zamanlayici.

`WhatsAppHandler` / `TelegramHandler` ile ayni yasam dongusu sozlesmesi:
    handler = SchedulerHandler(settings, engine=engine, broadcaster=broadcaster)
    task_group.create_task(handler.run(), name="scheduler_handler")
    ...
    handler.request_shutdown()

Isler (job):
  * ``reminders``       - her `scheduler_tick` sn: kullanicinin hatirlatici + rutinleri
                          (core/scheduler.py dosya tabanli mantigi; sesli komutla kurulanlar)
  * ``morning_briefing``- her gun `morning_briefing_time` (varsayilan 08:30): hava, bugunku
                          hatirlaticilar, okunmamis mailler, odevler -> model ozetler ->
                          JARVIS sesli soyler + Telegram/WhatsApp/ntfy'ye gonderir
  * ``health_check``    - her `health_check_interval_min` dk: CPU/RAM/disk; esik asilirsa uyari
  * ``daily_summary``   - her gun `daily_summary_time` (varsayilan 23:30): gunun konusma/not/
                          gorevlerinden Obsidian'a sessizce gun sonu ozeti (core/daily_summary.py);
                          PC o saatte kapaliysa acilista dun icin telafi edilir

Hata izolasyonu: her is `_guarded` icinde calisir; bir isin cokmesi zamanlayiciyi ya da
uygulamayi durdurmaz (loguru ile loglanir). APScheduler'in kendi hata/kacirma olaylari
da dinlenir.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from config.settings import Settings
from core.notifications import NotificationBroadcaster, build_broadcaster

_GUNLER = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
_DISABLED_WORDS = {"", "0", "off", "false", "kapali", "kapalı", "yok", "hayir", "hayır"}
HEALTH_ALERT_COOLDOWN_S = 6 * 3600

JobFn = Callable[[], Awaitable[Any]]


def parse_hhmm(value: str) -> tuple[int, int] | None:
    """'08:30' / '8.30' -> (8, 30); bos / 'kapali' / gecersiz -> None."""
    raw = (value or "").strip().lower()
    if raw in _DISABLED_WORDS:
        return None
    parts = raw.replace(".", ":").split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return None
    if 0 <= hour < 24 and 0 <= minute < 60:
        return hour, minute
    return None


_GOREV_RE = re.compile(r"^- \*\*(\d{2}):(\d{2})\*\* Zamanli gorev \((.+?)\): (.*)$")


def overnight_task_results(
    now: datetime, *, notes_dir: Path | None = None, since_hour: int = 18, excerpt: int = 400
) -> list[dict[str, str]]:
    """Dun `since_hour`'dan bu yana Obsidian `Notlar/` gunluk notlarina yazilmis zamanli
    gorev sonuclari (orchestrator._save_result_note) -> [{saat, ajan, gorev, sonuc}]."""
    if notes_dir is None:
        from tools.obsidian_sync import vault_dir

        base = vault_dir()
        if base is None:
            return []
        notes_dir = base / "Notlar"
    start = (now - timedelta(days=1)).replace(hour=since_hour, minute=0, second=0, microsecond=0)
    out: list[dict[str, str]] = []
    for day in (start.date(), now.date()):
        f = notes_dir / f"{day:%Y-%m-%d}.md"
        if not f.is_file():
            continue
        entry: dict[str, Any] | None = None
        body: list[str] = []

        def flush() -> None:
            if entry is not None:
                text = " ".join(" ".join(body).split())
                entry["sonuc"] = text[:excerpt] + ("..." if len(text) > excerpt else "")
                out.append(entry)

        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("- "):
                flush()
                entry, body = None, []
                m = _GOREV_RE.match(line)
                if m:
                    at = datetime.combine(day, datetime.min.time()).replace(
                        hour=int(m.group(1)), minute=int(m.group(2)))
                    if start <= at <= now:
                        entry = {"saat": f"{m.group(1)}:{m.group(2)}", "ajan": m.group(3),
                                 "gorev": m.group(4)[:120]}
            elif entry is not None and line.startswith("  "):
                body.append(line.strip())
        flush()
    return out


class SchedulerHandler:
    """Zamanlanmis gorevleri ve proaktif bildirimleri yoneten asenkron kol."""

    def __init__(
        self,
        settings: Settings,
        engine: Any = None,
        broadcaster: NotificationBroadcaster | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine  # BrainEngine (opsiyonel) - saglik raporunda oturum durumu
        self.broadcaster = broadcaster or build_broadcaster(settings)
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scheduler: Any = None
        # Duvar saati (time.time); diske yazilir ki yeniden baslatma bekleme suresini sifirlamasin.
        self._alert_state_path = Path(settings.data_dir) / "health_alerts.json"
        self._last_alert: dict[str, float] = {}
        try:
            saved = json.loads(self._alert_state_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self._last_alert = {k: float(v) for k, v in saved.items()}
        except (OSError, ValueError, TypeError):
            pass
        self._legacy: Any = None  # core.scheduler.Scheduler (hatirlatici/rutin mantigi)
        self.morning_at = parse_hhmm(settings.morning_briefing_time)
        self.summary_at = parse_hhmm(settings.daily_summary_time)

    # ------------------------------------------------------------------ yasam dongusu
    @property
    def enabled(self) -> bool:
        return bool(self.settings.scheduler_enabled)

    def request_shutdown(self) -> None:
        """Thread-safe: baska bir thread'den cagrilirsa kendi dongusune aktarilir."""
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                if asyncio.get_running_loop() is loop:
                    self._stop.set()
                    return
            except RuntimeError:
                pass
            loop.call_soon_threadsafe(self._stop.set)
        else:
            self._stop.set()

    async def run(self) -> None:
        """Zamanlayiciyi baslatir ve kapatma istegine kadar bekler. ASLA exception firlatmaz
        (iptal disinda); kapanista `scheduler.shutdown()` mutlaka cagrilir."""
        if not self.enabled:
            logger.info("[CRON] SCHEDULER_ENABLED=false - zamanlayici baslamadi.")
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
        except ImportError:
            logger.error("[CRON] APScheduler kurulu degil: pip install 'apscheduler>=3.10,<4'")
            return

        self._loop = asyncio.get_running_loop()
        try:
            self._legacy = self._make_legacy_scheduler()
            self._scheduler = AsyncIOScheduler(
                event_loop=self._loop,
                job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
            )
            self._register_jobs(self._scheduler)
            self._scheduler.start()
            logger.success(f"[CRON] Zamanlayici aktif - isler: {self.describe_jobs()}")
            await self._stop.wait()
        except asyncio.CancelledError:
            logger.info("[CRON] iptal sinyali alindi.")
            raise
        except Exception:  # noqa: BLE001 - zamanlayici beyni durdurmaz
            logger.exception("[CRON] zamanlayici beklenmedik sekilde sonlandi")
        finally:
            self._shutdown_scheduler()
            logger.info("[CRON] Zamanlayici durdu.")

    def _shutdown_scheduler(self) -> None:
        sched, self._scheduler = self._scheduler, None
        if sched is not None and getattr(sched, "running", False):
            try:
                sched.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                logger.exception("[CRON] scheduler.shutdown hatasi")

    # ------------------------------------------------------------------ isler
    def _register_jobs(self, sched: Any) -> None:
        from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED

        sched.add_listener(self._on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        s = self.settings
        sched.add_job(self._guarded("reminders", self.check_reminders), "interval",
                      seconds=max(3.0, s.scheduler_tick), id="reminders",
                      next_run_time=datetime.now() + timedelta(seconds=2))
        if self.morning_at:
            hour, minute = self.morning_at
            sched.add_job(self._guarded("morning_briefing", self.morning_briefing), "cron",
                          hour=hour, minute=minute, id="morning_briefing")
        if s.health_check_interval_min > 0:
            sched.add_job(self._guarded("health_check", self.health_check), "interval",
                          minutes=s.health_check_interval_min, id="health_check",
                          next_run_time=datetime.now() + timedelta(minutes=2))
        if s.maintenance_report_weekly:
            sched.add_job(self._guarded("maintenance_report", self.maintenance_report), "cron",
                          day_of_week="sun", hour=20, minute=0, id="maintenance_report")
        if self.summary_at:
            hour, minute = self.summary_at
            sched.add_job(self._guarded("daily_summary", self.daily_summary), "cron",
                          hour=hour, minute=minute, id="daily_summary")
            # dun PC ozet saatinde kapaliydiysa: acilistan kisa sure sonra bir kez telafi
            sched.add_job(self._guarded("daily_summary_catchup", self.daily_summary_catchup),
                          "date", run_date=datetime.now() + timedelta(seconds=90),
                          id="daily_summary_catchup")

    def _guarded(self, name: str, fn: JobFn) -> Callable[[], Awaitable[None]]:
        """Isi hata izolasyonuyla sarar: istisna loglanir, zamanlayici calismaya devam eder."""
        async def _job() -> None:
            started = time.monotonic()
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.bind(event="cron_job", job=name, ok=False).exception(f"[CRON] '{name}' isi coktu")
                return
            ms = int((time.monotonic() - started) * 1000)
            logger.bind(event="cron_job", job=name, ok=True, ms=ms).debug(f"[CRON] '{name}' tamam ({ms} ms)")

        _job.__name__ = f"job_{name}"
        return _job

    @staticmethod
    def _on_job_event(event: Any) -> None:
        if getattr(event, "exception", None):
            logger.error(f"[CRON] is hatasi ({event.job_id}): {event.exception!r}")
        else:
            logger.warning(f"[CRON] is zamaninda calisamadi (kacirildi): {event.job_id}")

    def describe_jobs(self) -> list[str]:
        if self._scheduler is None:
            return []
        out = []
        for job in self._scheduler.get_jobs():
            nxt = getattr(job, "next_run_time", None)
            out.append(f"{job.id}@{nxt:%d.%m %H:%M}" if nxt else job.id)
        return out

    async def run_job_now(self, job_id: str) -> None:
        """Bir isi beklemeden calistirir (test / yonetici komutu)."""
        jobs = {"reminders": self.check_reminders, "morning_briefing": self.morning_briefing,
                "health_check": self.health_check, "maintenance_report": self.maintenance_report,
                "daily_summary": self.daily_summary,
                "daily_summary_catchup": self.daily_summary_catchup}
        if job_id not in jobs:
            raise KeyError(f"bilinmeyen is: {job_id}")
        await self._guarded(job_id, jobs[job_id])()

    # ------------------------------------------------------------------ hatirlatici + rutin
    def _make_legacy_scheduler(self) -> Any:
        from agents.integrations.notifier import Notifier
        from core.scheduler import Scheduler

        try:
            from web.event_bus import BUS
        except Exception:  # noqa: BLE001
            BUS = None
        s = self.settings
        return Scheduler(
            data_dir=s.data_dir, outbox_path=s.agent_outbox_path, inbox_path=s.agent_inbox_path,
            tick=s.scheduler_tick, notifier=Notifier(s.ntfy_topic, s.ntfy_server), bus=BUS,
            # yeni sabah ozeti aciksa eski 09:00 "Gunluk Brifing" rutini kapatilir (cift brifing olmaz)
            default_briefing=self.morning_at is None,
        )

    async def check_reminders(self) -> None:
        """Vadesi gelen hatirlatici ve rutinleri tetikler (dosya IO -> thread)."""
        legacy = self._legacy or self._make_legacy_scheduler()
        self._legacy = legacy
        await asyncio.to_thread(legacy.tick_once)

    # ------------------------------------------------------------------ sabah ozeti
    async def morning_briefing(self) -> str:
        """Gunun ozetini toplar, modelle metne cevirir ve tum kanallara yollar."""
        facts = await asyncio.to_thread(self.collect_briefing_facts)
        text = await self.compose_briefing(facts)
        channels = self.settings.morning_briefing_channels or None
        await self.broadcaster.broadcast(text, channels)
        return text

    def collect_briefing_facts(self) -> dict[str, Any]:
        """Ozet icin ham bilgiler; her kaynak bagimsiz (biri hata verirse digerleri gelir)."""
        now = datetime.now()
        facts: dict[str, Any] = {"tarih": f"{now:%d.%m.%Y} {_GUNLER[now.weekday()]}"}

        try:
            from tools.quick_tools import get_weather

            w = get_weather(self.settings.hud_weather_location)
            if "error" not in w:
                today = (w.get("tahmin") or [{}])[0]
                facts["hava"] = {"konum": self.settings.hud_weather_location,
                                 "simdi": w.get("simdi"), "bugun": today}
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[CRON] hava alinamadi: {exc!r}")

        try:
            from core.scheduler import _load

            items = _load(self.settings.data_dir / "reminders.json")
            today = now.date().isoformat()
            facts["hatirlaticilar"] = [
                f"{r['fire_at'][11:16]} {r.get('text', '')}"
                for r in items if not r.get("done") and str(r.get("fire_at", "")).startswith(today)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[CRON] hatirlaticilar okunamadi: {exc!r}")

        try:
            from tools.email_tools import check_email, email_enabled

            if email_enabled():
                mails = check_email(unread_only=True, limit=5)
                if "error" not in mails:
                    facts["okunmamis_mail"] = [
                        f"{m.get('from', '?')}: {m.get('subject', '')}" for m in mails.get("messages", [])
                    ]
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[CRON] mailler okunamadi: {exc!r}")

        if self.settings.okul_enabled:
            try:
                from tools.okul_tool import okul_today_tasks

                tasks = okul_today_tasks()
                if "error" not in tasks:
                    facts["odevler"] = tasks
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[CRON] odevler okunamadi: {exc!r}")

        try:
            gece = overnight_task_results(now)
            if gece:
                facts["gece_gorevleri"] = gece
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[CRON] gece gorevleri okunamadi: {exc!r}")

        try:
            from core.daily_summary import read_section, summary_path

            base = self.settings.obsidian_dir
            if base is not None:
                kalan = read_section(summary_path(base, (now - timedelta(days=1)).date()),
                                     "Açık kalanlar")
                if kalan:
                    facts["dun_kalanlar"] = kalan[:600]
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[CRON] dunun ozeti okunamadi: {exc!r}")
        return facts

    async def compose_briefing(self, facts: dict[str, Any]) -> str:
        """Bilgileri kisa bir gunaydin mesajina cevirir: OpenRouter ('briefing' kanali) ->
        Gemini -> sablon. Model yoksa bile mesaj gider."""
        system = (
            "Sen JARVIS'sin, Sezai'nin kisisel asistani. Verilen JSON'dan Turkce, sicak ve kisa "
            "(en fazla 6 satir) bir gunaydin ozeti yaz: hava, bugunku hatirlaticilar, onemli "
            "okunmamis mailler, odevler. 'gece_gorevleri' varsa her gorev icin bir cumlelik "
            "sonuc ekle (bu kisim icin +6 satir serbest) ve detaylarin Obsidian'daki gunluk "
            "notta oldugunu soyle. 'dun_kalanlar' varsa dunden yarim kalan isleri bir-iki "
            "cumleyle hatirlat. Olmayan bilgiyi UYDURMA, bos alanlari atla. Emoji az."
        )
        prompt = json.dumps(facts, ensure_ascii=False, default=str)[:6000]

        if self.settings.openrouter_api_key:
            from core.openrouter_client import OpenRouterClient, default_chain

            client = OpenRouterClient(self.settings.openrouter_api_key)
            try:
                primary, *fallbacks = default_chain("briefing")
                text = await client.generate_response(
                    prompt, system_prompt=system, model=primary, fallback_models=fallbacks,
                    temperature=0.5, max_tokens=600,
                )
                if text.strip():
                    return text.strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[CRON] ozet icin OpenRouter basarisiz: {exc!r}")
            finally:
                await client.client.close()

        if self.settings.gemini_api_key:
            try:
                from google import genai
                from google.genai import types

                from agents.genai_util import generate_with_retry

                gclient = genai.Client(
                    api_key=self.settings.gemini_api_key,
                    http_options=types.HttpOptions(api_version=self.settings.agents_api_version),
                )
                resp = await generate_with_retry(
                    gclient, model=self.settings.agent_model_chain, contents=prompt,
                    config=types.GenerateContentConfig(system_instruction=system, temperature=0.5),
                    attempts=2,
                )
                if (getattr(resp, "text", "") or "").strip():
                    return resp.text.strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[CRON] ozet icin Gemini basarisiz: {exc!r}")

        return self.template_briefing(facts)

    @staticmethod
    def template_briefing(facts: dict[str, Any]) -> str:
        """Model yoksa kullanilan duz metin ozet."""
        lines = [f"Gunaydin Sezai! {facts.get('tarih', '')}"]
        hava = facts.get("hava") or {}
        simdi, bugun = hava.get("simdi") or {}, hava.get("bugun") or {}
        if simdi:
            lines.append(f"Hava ({hava.get('konum', '')}): {simdi.get('sicaklik')}°C, {simdi.get('durum', '')}"
                         + (f" (en dusuk {bugun.get('min')}°, en yuksek {bugun.get('max')}°)" if bugun else ""))
        if facts.get("hatirlaticilar"):
            lines.append("Bugun: " + "; ".join(facts["hatirlaticilar"]))
        if facts.get("okunmamis_mail"):
            lines.append(f"{len(facts['okunmamis_mail'])} okunmamis mail: "
                         + "; ".join(facts["okunmamis_mail"][:3]))
        if facts.get("gece_gorevleri"):
            lines.append(f"Gece {len(facts['gece_gorevleri'])} gorev tamamlandi: "
                         + ", ".join(g["ajan"] for g in facts["gece_gorevleri"])
                         + " (detaylar Obsidian gunluk notunda)")
        return "\n".join(lines)

    # ------------------------------------------------------------------ sistem sagligi
    def system_snapshot(self) -> dict[str, Any]:
        """CPU/RAM/disk yuzdeleri (psutil). Disk: verinin bulundugu surucu."""
        import psutil

        anchor = Path(self.settings.data_dir).resolve().anchor or "/"
        return {
            "cpu": psutil.cpu_percent(interval=1.0),
            "mem": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage(anchor).percent,
            "brain_session": bool(getattr(self.engine, "session_active", False)) if self.engine else None,
        }

    async def health_check(self) -> dict[str, Any]:
        """Kaynaklari olcer, loglar; esik asildiysa (6 saatte en fazla bir kez) kanallara uyari."""
        snap = await asyncio.to_thread(self.system_snapshot)
        s = self.settings
        logger.bind(event="health", **{k: v for k, v in snap.items() if v is not None}).info(
            f"[CRON] Sistem sagligi: CPU %{snap['cpu']:.0f} · RAM %{snap['mem']:.0f} · "
            f"Disk %{snap['disk']:.0f}"
            + ("" if snap["brain_session"] is None else
               f" · sesli beyin {'bagli' if snap['brain_session'] else 'BAGLI DEGIL'}")
        )
        limits = {"cpu": ("CPU", s.health_cpu_alert), "mem": ("RAM", s.health_mem_alert),
                  "disk": ("Disk", s.health_disk_alert)}
        now = time.time()
        alerts = []
        for key, (label, limit) in limits.items():
            if snap[key] >= limit and now - self._last_alert.get(key, -1e9) >= HEALTH_ALERT_COOLDOWN_S:
                self._last_alert[key] = now
                alerts.append(f"{label} %{snap[key]:.0f} (esik %{limit:.0f})")
                if key == "disk":
                    hint = await self._cleanup_hint()
                    if hint:
                        alerts[-1] += f" - {hint}"
        if alerts:
            try:
                self._alert_state_path.write_text(json.dumps(self._last_alert), encoding="utf-8")
            except OSError as exc:
                logger.debug(f"Saglik uyari durumu yazilamadi: {exc}")
            await self.broadcaster.broadcast("Sistem uyarisi: " + ", ".join(alerts))
        snap["alerts"] = alerts
        return snap

    # ------------------------------------------------------------------ disk bakimi
    async def _cleanup_hint(self) -> str:
        """Disk uyarisina eklenecek tek satirlik temizlik ozeti (tarama silmez)."""
        from tools.maintenance import cleanup_scan, scan_summary

        try:
            scan = await asyncio.to_thread(cleanup_scan)
        except Exception as exc:  # noqa: BLE001 - uyari yine gider
            logger.debug(f"Disk taramasi yapilamadi: {exc!r}")
            return ""
        if scan["reclaimable_mb"] < 500:
            return ""
        return f"{scan_summary(scan)}. 'JARVIS temizlik yap' de."

    async def daily_summary(self) -> Path | None:
        """Bugunun gun sonu ozetini Obsidian'a yazar (sessiz; sesli okunmaz)."""
        from core import daily_summary

        return await daily_summary.run(self.settings, datetime.now().date())

    async def daily_summary_catchup(self) -> Path | None:
        """Dunun kaydi var ama ozeti yoksa simdi uretir."""
        from core import daily_summary

        yesterday = (datetime.now() - timedelta(days=1)).date()
        if not await asyncio.to_thread(daily_summary.missing_for, self.settings, yesterday):
            return None
        return await daily_summary.run(self.settings, yesterday)

    async def maintenance_report(self) -> dict[str, Any]:
        """Haftalik bakim raporu: disk durumu + temizlenebilir alan. Hicbir sey silmez."""
        from tools.maintenance import cleanup_scan, scan_summary
        from tools.obsidian_sync import append_note

        scan = await asyncio.to_thread(cleanup_scan)
        disk = scan["disk"]
        text = (f"Haftalik bakim: C: %{disk['used_percent']:.0f} dolu, {disk['free_gb']:.0f} GB bos. "
                f"{scan_summary(scan)}.")
        if scan["reclaimable_mb"] >= 1024:
            text += " Temizlik icin 'JARVIS temizlik yap' de."
        await asyncio.to_thread(append_note, text)
        await self.broadcaster.broadcast(text)
        return {"text": text, "scan": scan}
