"""Eski yonlendirme (Conductor LLM) ile yeni router'i karsilastirir.

    python scripts/router_benchmark.py              # yalnizca yerel router; API cagrisi YOK
    python scripts/router_benchmark.py --live 8     # eski yontemi 8 istekte gercekten olcer
                                                    # (Conductor LLM; ucretsiz kota harcar)

Eski yontemin karar suresi --live verilmezse gecmis gorev loglarindan (bridge/inbox.txt +
data/task_logs.jsonl) hesaplanir. "Toplam" suresi = karar + gecmis ortanca ajan calisma suresi
(tahmin; ajanlar bu betikte calistirilmaz).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics as st
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (istek, beklenen gorev tipi, beklenen ajan) - examples.yaml'da OLMAYAN cumleler
CASES: list[tuple[str, str, str | None]] = [
    ("Sistem belleği %95, arka plan uygulamalarını ve başlangıç öğelerini incele", "sistem_komutu", "sistem_sagligi"),
    ("Günlük brifing: okunmamış önemli mailler, bugünün havası ve hatırlatıcılar", "iletisim", "gunluk_brifing"),
    ("Disk doluluk uyarısından sonra temizlik başlat", "sistem_komutu", "bakim_teknisyeni"),
    ("Bugün yapmamız gerekenleri sırala ve önceliklendir", "planlama", "planlayici"),
    ("Tarkan'dan bir şarkı çal", "sistem_komutu", "muzik_dj"),
    ("Kotlin ile Android geliştirme hakkında detaylı araştırma yap ve kaynak ver", "arastirma", "arastirmaci"),
    ("agents klasöründeki python kodunu güvenlik açısından incele", "kod", "kod_denetcisi"),
    ("yarın sabah dersim var mı", "okul", "ders_programi"),
    ("Matematik vizesine 5 gün kaldı, gün gün çalışma planı yap", "okul", "sinav_kocu"),
    ("hocama ödev süresinin uzatılması için kibar bir yanıt taslağı yaz", "iletisim", "yanit_taslakcisi"),
    ("İzmir'de yarın hava nasıl olacak", "sohbet", "hava_durumu"),
    ("Konak'tan Buca'ya hangi otobüsle giderim", "sistem_komutu", "ulasim"),
    ("flask uygulamasına giriş sayfası ekle ve dosyaya kaydet", "kod", "kodcu"),
    ("geçen hafta harcadığım parayı topla", "planlama", "harcama_defteri"),
    ("research the history of the Ottoman empire with sources", "arastirma", "arastirmaci"),
    ("open notepad", "sistem_komutu", "pc_operatoru"),
    ("bana moral verecek bir şey söyle", "sohbet", None),
    ("GANO'm 2.8, 3'e çıkarmak için ne almam lazım", "okul", "gano_danismani"),
    ("teslim tarihi geçmiş ödevler hangileri", "okul", "odev_takipcisi"),
    ("Bilişim dersi notlarımdan sınav soruları çıkar", "okul", "not_ozetleyici"),
    ("gelen kutumda önemli bir şey var mı", "iletisim", "eposta_triyaj"),
    ("sınıf whatsapp grubuna yarınki toplantı için duyuru yaz", "yazi", "mesaj_yazari"),
    ("Chrome'da deu.edu.tr'yi aç", "sistem_komutu", "pc_operatoru"),
    ("ESHOT sitesinde Buca hattıyla ilgili duyuru var mı bak", "sistem_komutu", "web_operatoru"),
    ("işlemciyi en çok yoran programlar hangileri", "sistem_komutu", "sistem_sagligi"),
    ("package.json'daki kütüphanelerde güvenlik açığı var mı", "kod", "bagimlilik_gozcusu"),
    ("bu projede hangi testler eksik", "kod", "test_kocu"),
    ("telefonda instagramı aç", "sistem_komutu", "telefon_operatoru"),
    ("bunu bilgi bankasına kaydet: router 2026-10-28'de eklendi", "sohbet", "bilgi_bankasi"),
    ("dün ne not almıştım", "sohbet", "not_katibi"),
    ("bu PDF'in ana fikirlerini çıkar", "yazi", "belge_ozetleyici"),
    ("her cuma 17:00'de haftalık değerlendirme hatırlat", "planlama", "hatirlatici"),
    ("markette 230 lira harcadım, deftere yaz", "planlama", "harcama_defteri"),
    ("yazdığın betiği çalıştır ve çıktıyı doğrula", "kod", "bilgisayar_op"),
    ("telegramda yeni mesaj var mı", "iletisim", "sekreter"),
    ("bu ekran görüntüsündeki hatayı açıkla", "gorsel", None),
    ("bir mikroservis mimarisi tasarla, hata toleransı ve testleriyle birlikte", "kod", "kodcu"),
    ("Notion'daki yapılacaklar listemi getir", "sistem_komutu", "entegrasyon_uzmani"),
    ("masaüstündeki dosyaları türüne göre klasörle", "sistem_komutu", "dosya_duzenleyici"),
    ("selam jarvis, naber", "sohbet", None),
]


def _rows(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def historical_timings() -> dict[str, float | int | None]:
    """inbox.txt (istek zamani) + task_logs.jsonl (running/done) -> eski karar ve calisma sureleri."""
    inbox = {r["id"]: r for r in _rows(ROOT / "bridge" / "inbox.txt") if "id" in r}
    running, done = {}, {}
    for r in _rows(ROOT / "data" / "task_logs.jsonl"):
        if r.get("status") == "running" and r.get("id") not in running:
            running[r["id"]] = r
        if r.get("status") in ("done", "failed"):
            done[r["id"]] = r
    decide, work = [], []
    for task_id, req in inbox.items():
        if task_id not in running:
            continue
        try:
            t0 = datetime.fromisoformat(req["created_at"])
            t1 = datetime.fromisoformat(running[task_id]["updated_at"])
        except (KeyError, ValueError):
            continue
        if req.get("agent", "auto") == "auto" and 0 <= (t1 - t0).total_seconds() < 600:
            decide.append((t1 - t0).total_seconds())
        if task_id in done:
            try:
                t2 = datetime.fromisoformat(done[task_id]["updated_at"])
                if 0 <= (t2 - t1).total_seconds() < 900:
                    work.append((t2 - t1).total_seconds())
            except (KeyError, ValueError):
                pass
    return {
        "decide_median_s": st.median(decide) if decide else None, "decide_n": len(decide),
        "work_median_s": st.median(work) if work else None, "work_n": len(work),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", type=int, default=0, help="eski Conductor LLM'ini bu kadar istekte gercekten olc")
    args = parser.parse_args()

    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING", format="{message}")

    from agents.registry import load_agents
    from config.settings import get_settings
    from router import RouteRequest, build_router

    settings = get_settings().model_copy(update={"routing_log_path": None})
    agents = load_agents(settings.agent_config_path)
    llm_calls: list[str] = []

    async def counting_llm(prompt: str) -> str:
        # Burada ag YOK: router'in kisa LLM sorusuna KAC KEZ ihtiyac duydugunu sayar.
        llm_calls.append(prompt)
        raise RuntimeError("benchmark: LLM cagrisi sayildi (yapilmadi)")

    router = build_router(settings, agents=agents, llm_ask=counting_llm)
    t = time.perf_counter()
    if not router.classifier.embedder.load():
        print("HATA: yerel gomme modeli yuklenemedi.")
        return
    router.classifier.fit()
    router.classifier.embed("isinma")
    prep = time.perf_counter() - t
    reg = router.registry

    print(f"\nRouter hazirlik (acilista bir kez, arka planda): {prep:.1f} sn\n")
    head = f"{'ms':>6}  {'gorev':13} {'zrl':5} {'g.guv':>5}  {'ajan':18} {'a.guv':>5}  {'model':34} istek"
    print(head)
    print("-" * len(head))
    lat, ok_task, ok_agent, n_agent, would_llm, would_task_llm = [], 0, 0, 0, 0, 0
    model_count: dict[str, int] = {}
    for text, exp_task, exp_agent in CASES:
        before = len(llm_calls)
        d = await router.route(RouteRequest(text=text, pick_agent=True, needs_tools=True))
        agent = d.agent
        hint = agents[agent].model if agent in agents else None
        d = router.reroute_for_agent(d, agent=agent, hint=hint, needs_tools=True, source="classifier",
                                     confidence=d.agent_confidence)
        lat.append(d.latency_ms)
        low_agent = (d.agent_confidence or 0) < reg.agent_threshold      # -> Conductor LLM (~10 sn)
        low_task = len(llm_calls) > before   # router kisa JSON sorusuna ihtiyac duydu
        would_llm += low_agent
        would_task_llm += low_task
        low = low_agent
        ok_task += d.task_type == exp_task
        if exp_agent:
            n_agent += 1
            ok_agent += agent == exp_agent
        model_count[d.model_id] = model_count.get(d.model_id, 0) + 1
        mark_t = "+" if d.task_type == exp_task else "x"
        mark_a = "" if not exp_agent else ("+" if agent == exp_agent else "x")
        print(f"{d.latency_ms:6.1f}  {d.task_type:12}{mark_t} {d.difficulty:5} {d.confidence:5.2f}  "
              f"{str(agent):17}{mark_a or ' '} {d.agent_confidence or 0:5.2f}  {d.model_id[:34]:34} "
              f"{'[AJAN-LLM] ' if low else ''}{'[GOREV-LLM] ' if low_task else ''}{text[:40]}")

    hist = historical_timings()
    live_times: list[float] = []
    task_llm_times: list[float] = []
    if args.live:
        from google import genai
        from google.genai import types

        from agents.conductor import Conductor
        from agents.genai_util import generate_with_retry
        from agents.registry import load_orchestrator_config
        from core.openrouter_client import OpenRouterClient
        from router.llm_fallback import LlmRouter

        cfg = load_orchestrator_config(settings.agent_config_path)
        client = genai.Client(api_key=settings.gemini_api_key,
                              http_options=types.HttpOptions(api_version=settings.agents_api_version))
        conductor = Conductor(client, settings.agent_model_chain, agents=agents,
                              openrouter=OpenRouterClient(settings.openrouter_api_key or None),
                              openrouter_models=[cfg.get("default_model"), *cfg.get("fallback_models", [])])
        print()
        print(f"Eski yontem canli olculuyor ({args.live} istek, Conductor LLM)...")
        for text, _, _ in CASES[: args.live]:
            t = time.perf_counter()
            dec = await conductor.route(text)
            live_times.append(time.perf_counter() - t)
            print(f"  {live_times[-1]:5.1f} sn  {dec.agent:18} {text[:50]}")

        async def ask(prompt: str) -> str:
            resp = await generate_with_retry(
                client, model=reg.llm_models, contents=prompt, attempts=1,
                config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json"))
            return resp.text or ""

        llm = LlmRouter(ask, task_types=reg.task_types, timeout_s=reg.llm_timeout)
        print()
        print(f"Router'in kisa LLM sorusu canli olculuyor ({args.live} istek, {reg.llm_models[0]})...")
        for text, _, _ in CASES[: args.live]:
            t = time.perf_counter()
            try:
                verdict = await llm.classify(text)
                label = f"{verdict.task_type}/{verdict.difficulty}"
            except Exception as exc:  # noqa: BLE001
                label = f"HATA {type(exc).__name__}"
            task_llm_times.append(time.perf_counter() - t)
            print(f"  {task_llm_times[-1]:5.1f} sn  {label:24} {text[:44]}")

    n = len(CASES)
    lat_sorted = sorted(lat)
    p90 = lat_sorted[max(0, int(n * 0.9) - 1)]
    old_decide = st.median(live_times) if live_times else hist["decide_median_s"]
    old_src = f"canli, n={len(live_times)}" if live_times else f"gecmis loglar, n={hist['decide_n']}"
    task_llm = st.median(task_llm_times) if task_llm_times else None
    work = hist["work_median_s"]
    share_agent, share_task = would_llm / n, would_task_llm / n
    # Beklenen karar = yerel + (ajan guveni dusukse Conductor LLM) + (gorev guveni dusukse kisa LLM)
    new_decide_s = st.median(lat) / 1000 + share_agent * (old_decide or 0) + share_task * (task_llm or 0)

    print()
    print("=== OZET ===")
    print(f"{'':36}{'ESKI (Conductor LLM)':>26}{'YENI (router)':>22}")
    print(f"{'Yerel karar suresi (ortanca)':36}{'-':>26}{f'{st.median(lat):.1f} ms':>22}")
    print(f"{'Yerel karar (p90 / en kotu)':36}{'-':>26}{f'{p90:.1f} / {lat_sorted[-1]:.1f} ms':>22}")
    print(f"{'Ajan icin Conductor LLM (~10 sn)':36}{'%100':>26}{f'%{share_agent * 100:.0f} ({would_llm}/{n})':>22}")
    print(f"{'Gorev/zorluk icin kisa LLM sorusu':36}{'-':>26}{f'%{share_task * 100:.0f} ({would_task_llm}/{n})':>22}")
    if task_llm is not None:
        print(f"{'  kisa LLM sorusu suresi (ortanca)':36}{'-':>26}{f'{task_llm:.1f} sn':>22}")
    print(f"{'Karar suresi (ortanca, ESKI)':36}{(f'{old_decide:.1f} sn ({old_src})' if old_decide else '-'):>26}{'':>22}")
    estimate = "" if task_llm is not None else " *"
    print(f"{'Beklenen karar (LLM paylari dahil)':36}{(f'{old_decide:.1f} sn' if old_decide else '-'):>26}"
          f"{f'{new_decide_s:.1f} sn{estimate}':>22}")
    if work and old_decide:
        print(f"{'Toplam (karar + ajan, tahmin)':36}{f'{old_decide + work:.1f} sn':>26}"
              f"{f'{new_decide_s + work:.1f} sn{estimate}':>22}")
        print(f"  ajan calisma ortancasi gecmis loglardan: {work:.1f} sn (n={hist['work_n']})")
    if task_llm is None:
        print("  * kisa LLM sorusunun suresi dahil degil; olcmek icin: --live 8")
    print()
    print(f"Dogruluk (yerel, LLM'siz): gorev tipi {ok_task}/{n}, ajan {ok_agent}/{n_agent}")
    print("Secilen modeller: " + ", ".join(f"{m} x{c}" for m, c in sorted(model_count.items(), key=lambda x: -x[1])))
    print("Eski yontemde model sabitti: agents.json'daki ajan modeli (29/35 ajan gemini-flash-lite-latest).")


if __name__ == "__main__":
    asyncio.run(main())
