"""Dogrulama betigi: bulut zinciri tamamen dusunce yerel model (Ollama) devralir mi?

Calistir:  python scripts/test_local_fallback.py   (Ollama acik olmali)

Gemini zinciri bilerek var olmayan bir modele ayarlanir (404). Beklenen:
  1. Conductor yonlendirmesi yerel modelle yapilir ("[YEDEK MODEL ollama/...]").
  2. Aracli bir ajan (OKUL / odev_takipcisi) yerel modelle GERCEKTEN arac cagirir.
  3. Sonuc yedek modeli acikca belirtir (sessiz yedek yok).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google import genai  # noqa: E402
from loguru import logger  # noqa: E402

from agents.agent import Agent  # noqa: E402
from agents.conductor import Conductor  # noqa: E402
from agents.registry import load_agents  # noqa: E402
from config.settings import get_settings  # noqa: E402
from core.local_llm import get_local_llm  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
BROKEN_CHAIN = ["gemini-yok-404"]


async def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{message}")
    settings = get_settings()
    local = get_local_llm()
    if local is None or not await local.is_up():
        print(f"{FAIL} Yerel model kapali/erisilemiyor (JARVIS_LOCAL_LLM / Ollama)")
        return 1

    client = genai.Client(api_key=settings.gemini_api_key or "yok")
    agents = load_agents(None)  # agents.json override'i yok: Claude/OpenRouter devre disi
    ok = True

    started = time.monotonic()
    conductor = Conductor(client, BROKEN_CHAIN, agents=agents)
    decision = await conductor.route("Bu hafta teslim edilecek odevlerim neler?")
    print(f"\nConductor ({time.monotonic() - started:.1f} sn): {decision}")
    good = "YEDEK MODEL ollama/" in decision.reason
    ok &= good
    print(f"{PASS if good else FAIL} yonlendirme yerel modelle yapildi")

    started = time.monotonic()
    agent = Agent(agents["odev_takipcisi"], client, default_models=BROKEN_CHAIN,
                  default_max_steps=4)
    result = await agent.run("Bu hafta teslim edilecek odevlerimi listele.")
    print(f"\nAjan ({time.monotonic() - started:.1f} sn): model={result.model} "
          f"fallback={result.fallback} araclar={result.tool_calls}\n{result.text[:600]}")
    checks = [
        ("ajan basarili", result.ok),
        ("yanit yerel modelden", str(result.model).startswith("ollama/")),
        ("yedek acikca isaretli", result.fallback and result.primary_model == BROKEN_CHAIN[0]),
        ("okul araci cagrildi", any(t.startswith("okul_") for t in result.tool_calls)),
    ]
    for name, cond in checks:
        ok &= bool(cond)
        print(f"{PASS if cond else FAIL} {name}")
    print("\nSONUC:", "TAMAM" if ok else "BASARISIZ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
