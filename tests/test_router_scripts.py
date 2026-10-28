"""scripts/router_retrain.py veri birlestirme mantigi (gomme/sklearn olmadan)."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALID = {"task_types": {"kod", "sohbet"}, "difficulty": {"basit", "orta", "zor"}, "agents": {"kodcu", "muzik_dj"}}
LOG = [
    {"kind": "decision", "request": "python kodu yaz", "task_type": "kod", "difficulty": "orta",
     "source": "classifier", "confidence": 0.95, "rule": None, "agent": "kodcu", "agent_confidence": 0.97},
    {"kind": "decision", "request": "belirsiz istek", "task_type": "sohbet", "difficulty": "basit",
     "source": "classifier", "confidence": 0.4, "rule": None, "agent": "muzik_dj", "agent_confidence": 0.5},
    {"kind": "decision", "request": "sarki cal", "task_type": "kod", "difficulty": "zor",
     "source": "classifier", "confidence": 0.95, "rule": None, "agent": "kodcu", "agent_confidence": 0.95},
    {"kind": "done", "request_id": "x"},
]


def test_low_confidence_decisions_are_not_self_labels(tmp_path):
    rt = _load("router_retrain")
    data = rt.build_dataset({}, LOG, tmp_path / "yok.csv", VALID)
    texts = {t for t, _, _ in data["task_types"]}
    assert "python kodu yaz" in texts and "belirsiz istek" not in texts


def test_user_corrections_win_and_weigh_more(tmp_path):
    rt = _load("router_retrain")
    labels = tmp_path / "labels.csv"
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rt.CSV_FIELDS)
        writer.writeheader()
        writer.writerow({"text": "sarki cal", "task_type": "sohbet", "difficulty": "basit", "agent": "muzik_dj"})
        writer.writerow({"text": "python kodu yaz", "task_type": "uydurma"})
    data = rt.build_dataset({}, LOG, labels, VALID)
    assert ("sarki cal", "muzik_dj", 3) in data["agents"]
    assert ("sarki cal", "kod", 1) not in data["task_types"]          # yanlis oz-etiket ezildi
    assert not any(lab == "uydurma" for _, lab, _ in data["task_types"])  # gecersiz etiket atlandi


def test_export_appends_only_new_decisions(tmp_path):
    rt = _load("router_retrain")
    path = tmp_path / "labels.csv"
    assert rt.export_labels(LOG, path) == 3
    assert rt.export_labels(LOG, path) == 0
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert {r["text"] for r in rows} == {"python kodu yaz", "belirsiz istek", "sarki cal"}
