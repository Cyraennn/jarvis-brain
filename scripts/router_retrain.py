"""Router siniflandiricisini loglardan + duzeltilmis etiketlerden yeniden egitir.

    python scripts/router_retrain.py --export        # son kararlari data/router_labels.csv'ye dok
      -> CSV'de yanlis olan task_type / difficulty / agent hucrelerini duzelt (bos = dokunma)
    python scripts/router_retrain.py                 # egit, dogrulugu raporla, data/router_model.npz yaz
    python scripts/router_retrain.py --dry-run       # yalnizca rapor, dosya yazma

Egitim verisi (agirlik):
  - router/examples.yaml prototipleri                                  x1
  - routing.jsonl'deki guvenilir kararlar (kural / LLM / guven >= 0.9)  x1  (oz-etiket)
  - data/router_labels.csv'deki SENIN etiketlerin                       x3  (her zaman kazanir)
Model pickle DEGIL, yalnizca sayi dizileriyle (.npz) saklanir. JARVIS bir sonraki acilista
otomatik kullanir; dosyayi silmek prototip yontemine geri doner.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEADS = ("task_types", "difficulty", "agents")
CSV_FIELDS = ["text", "task_type", "difficulty", "agent", "model_secimi", "kaynak"]
LOG_FIELD = {"task_types": "task_type", "difficulty": "difficulty", "agents": "agent"}


def _decisions(log_rows: list[dict]) -> list[dict]:
    return [r for r in log_rows if r.get("kind") == "decision" and r.get("request")
            and not str(r.get("request_id", "")).endswith("-qa")]


def export_labels(log_rows: list[dict], path: Path) -> int:
    existing = set()
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            existing = {row["text"] for row in csv.DictReader(handle)}
    new = [r for r in _decisions(log_rows) if r["request"] not in existing]
    write_header = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for r in new:
            writer.writerow({"text": r["request"], "task_type": r.get("task_type", ""),
                             "difficulty": r.get("difficulty", ""), "agent": r.get("agent") or "",
                             "model_secimi": r.get("model_id", ""), "kaynak": r.get("source", "")})
    return len(new)


def build_dataset(examples: dict, log_rows: list[dict], labels_path: Path,
                  valid: dict[str, set[str]]) -> dict[str, list[tuple[str, str, int]]]:
    """{bas: [(metin, etiket, agirlik)]}"""
    data: dict[str, list[tuple[str, str, int]]] = {h: [] for h in HEADS}
    for head in HEADS:
        for label, texts in (examples.get(head) or {}).items():
            data[head] += [(t, label, 1) for t in texts]

    corrected: dict[str, dict[str, str]] = {}
    if labels_path.exists():
        with labels_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                corrected[row.get("text", "")] = row

    for r in _decisions(log_rows):
        text = r["request"]
        if text in corrected:
            continue   # kullanici etiketi asagida eklenir
        trusted_task = r.get("source") in ("rule", "llm_fallback") or (r.get("confidence") or 0) >= 0.9
        if trusted_task and r.get("rule") is None:
            data["task_types"].append((text, r["task_type"], 1))
            data["difficulty"].append((text, r["difficulty"], 1))
        if r.get("agent") and (r.get("agent_source") in ("conductor_llm", "explicit")
                               or (r.get("agent_confidence") or 0) >= 0.9):
            data["agents"].append((text, r["agent"], 1))

    for text, row in corrected.items():
        for head in HEADS:
            label = (row.get(LOG_FIELD[head]) or "").strip()
            if label and label in valid[head]:
                data[head].append((text, label, 3))
            elif label:
                print(f"  ! gecersiz etiket atlandi ({LOG_FIELD[head]}={label!r}): {text[:50]}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", action="store_true", help="kararlari duzeltme icin CSV'ye dok")
    parser.add_argument("--dry-run", action="store_true", help="egit ve raporla ama dosya yazma")
    args = parser.parse_args()

    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING", format="{message}")

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    from agents.registry import load_agents
    from config.settings import get_settings
    from router.classifier import load_examples, save_trained
    from router.embedder import E5Embedder
    from router.log import RoutingLog
    from router.registry import ModelRegistry

    settings = get_settings()
    labels_path = settings.data_dir / "router_labels.csv"
    log_rows = RoutingLog(settings.routing_log_path).read()

    if args.export:
        added = export_labels(log_rows, labels_path)
        print(f"{added} yeni karar eklendi -> {labels_path}")
        print("Yanlis olan task_type / difficulty / agent hucrelerini duzeltip betigi tekrar calistir.")
        return

    registry = ModelRegistry.load(settings.router_config_path)
    agents = load_agents(settings.agent_config_path)
    valid = {"task_types": set(registry.task_types) - {"qa"}, "difficulty": {"basit", "orta", "zor"},
             "agents": set(agents)}
    examples = load_examples(settings.router_examples_path)
    from router import agent_prototypes

    for name, texts in agent_prototypes(agents).items():
        examples["agents"].setdefault(name, [])
        examples["agents"][name] = examples["agents"][name] + texts

    data = build_dataset(examples, log_rows, labels_path, valid)
    embedder = E5Embedder()
    if not embedder.load():
        print(f"HATA: gomme modeli yuklenemedi: {embedder.error}")
        return

    heads = {}
    print(f"Log kararlari: {len(_decisions(log_rows))} | etiket dosyasi: "
          f"{'var' if labels_path.exists() else 'yok'} ({labels_path})\n")
    for head in HEADS:
        rows = [(t, lab, w) for t, lab, w in data[head] if lab in valid[head]]
        texts = [t for t, _, _ in rows]
        y = np.array([lab for _, lab, _ in rows])
        weights = np.array([w for _, _, w in rows], dtype=np.float64)
        x = embedder.embed(texts)
        counts = Counter(y)
        model = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")
        folds = min(5, min(counts.values())) if counts else 0
        if folds >= 2:
            acc = cross_val_score(LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"),
                                  x, y, cv=folds).mean()
            acc_txt = f"capraz dogrulama dogrulugu %{acc * 100:.0f} ({folds} katli)"
        else:
            acc_txt = "capraz dogrulama icin sinif basina ornek az"
        model.fit(x, y, sample_weight=weights)
        heads[head] = model
        user = int((weights == 3).sum())
        print(f"{head:11} {len(rows):4} ornek ({user} senin etiketin), {len(counts)} sinif - {acc_txt}")

    if args.dry_run:
        print("\n--dry-run: model yazilmadi.")
        return
    save_trained(settings.router_model_path, heads)
    print(f"\nModel yazildi: {settings.router_model_path}")
    print("JARVIS'i yeniden baslatinca kullanilir. Geri almak icin dosyayi silmen yeterli.")


if __name__ == "__main__":
    main()
