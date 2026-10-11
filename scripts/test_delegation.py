"""Dogrulama betigi: JARVIS (Conductor) -> SISTEM departmani -> Markdown Denetcisi.

Calistir:  python scripts/test_delegation.py

Senaryo:
  1. Bilerek sorunlu bir markdown dosyasi olusturulur.
  2. "auto" bir gorev orkestratore verilir.
  3. Conductor'un SISTEM/markdown_denetcisi'ne yonlendirdigi dogrulanir.
  4. Ajan (skill + LLM) calistirilir; raporun sorunlari yakaladigi dogrulanir.
  5. Sonucun bridge/outbox.txt'e yazildigi dogrulanir.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from agents.conductor import Conductor  # noqa: E402
from agents.orchestrator import AgentOrchestrator  # noqa: E402
from agents.schemas import Department, TaskRequest  # noqa: E402
from agents.skills.markdown_auditor import audit_markdown  # noqa: E402
from config.settings import get_settings  # noqa: E402

_BAD_MD = """## Yanlis seviyeden baslayan baslik

#### Atlanan seviye

Bir [kirik baglanti](./olmayan-dosya.md) var.
Ve alt metni olmayan ![](resim.png).

Ciplak URL: https://example.com

- tire
* yildiz

TODO: bunu duzelt
"""

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


async def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")

    settings = get_settings()
    sandbox = settings.data_dir / "delegation_test"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "bozuk.md").write_text(_BAD_MD, encoding="utf-8")
    (settings.agent_outbox_path).write_text("", encoding="utf-8")

    ok = True

    # --- 1) skill dogrudan calisiyor mu ---
    report = audit_markdown(target=str(sandbox))
    hit = report.get("totals", {})
    skill_ok = hit.get("error", 0) >= 2 and hit.get("warning", 0) >= 2
    print(f"[{PASS if skill_ok else FAIL}] markdown_auditor yetenegi sorunlari yakaladi "
          f"(hata={hit.get('error')}, uyari={hit.get('warning')}, bilgi={hit.get('info')})")
    ok &= skill_ok

    # --- 2) Conductor dogru yonlendiriyor mu ---
    orch = AgentOrchestrator(settings)
    conductor: Conductor = orch.conductor
    task = f"{sandbox} klasorundeki markdown dosyalarinda baslik ve baglanti sorunlarini denetle"
    decision = await conductor.route(task)
    route_ok = decision.agent == "markdown_denetcisi" and decision.department == Department.SISTEM
    print(f"[{PASS if route_ok else FAIL}] Conductor -> departman={decision.department}, "
          f"ajan={decision.agent}  (gerekce: {decision.reason})")
    ok &= route_ok

    # --- 3) tam akis: orkestrator gorevi isliyor mu ---
    seen: list = []
    orch.observer.on_task = lambda u: seen.append((u.status, u.agent, u.department))  # type: ignore
    request = TaskRequest(agent="auto", task=task, source="test")
    await orch._handle(request)

    statuses = [s for s, _, _ in seen]
    flow_ok = "running" in statuses and ("done" in statuses)
    print(f"[{PASS if flow_ok else FAIL}] akis: {' -> '.join(statuses)}")
    ok &= flow_ok

    # --- 4) outbox yazildi mi ---
    out = settings.agent_outbox_path.read_text(encoding="utf-8").strip()
    outbox_ok = "Markdown Denetçisi" in out and len(out) > 20
    print(f"[{PASS if outbox_ok else FAIL}] outbox: {out[:140]}")
    ok &= outbox_ok

    print("\n" + ("\033[92mTUM TESTLER GECTI\033[0m" if ok else "\033[91mBAZI TESTLER BASARISIZ\033[0m"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
