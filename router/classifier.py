"""Yerel siniflandirici: gorev tipi + zorluk (+ ajan secimi icin ayni motor).

Varsayilan: egitimsiz "prototip" yontemi - her sinifin ornek cumlelerine (router/examples.yaml)
kosinus benzerligi; sinif skoru = en yakin k ornegin ortalamasi; guven = en iyi iki sinifin
skor farkinin sigmoid'i (cok sinifta softmax guveni yapay olarak dusurur).
`scripts/router_retrain.py` ile egitilmis bir model (data/router_model.npz) varsa o bas icin
logistic regression kullanilir (predict_proba = guven).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from loguru import logger

from router.embedder import Embedder


@dataclass
class Prediction:
    label: str
    confidence: float
    scores: list[tuple[str, float]] = field(default_factory=list)   # en iyi 3 (etiket, benzerlik/olasilik)
    method: str = "prototype"   # prototype | trained

    def top(self) -> list[dict[str, Any]]:
        return [{"label": k, "p": round(v, 3)} for k, v in self.scores]


def load_examples(path: Path | str) -> dict[str, dict[str, list[str]]]:
    """examples.yaml -> {"task_types": {..}, "difficulty": {..}, "agents": {..}}"""
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    out: dict[str, dict[str, list[str]]] = {}
    for head in ("task_types", "difficulty", "agents"):
        table = data.get(head) or {}
        out[head] = {str(k): [str(x) for x in (v or []) if str(x).strip()] for k, v in table.items()}
    return out


def _softmax(values: np.ndarray, temperature: float) -> np.ndarray:
    z = (values - values.max()) / max(temperature, 1e-6)
    e = np.exp(z)
    return e / e.sum()


class PrototypeClassifier:
    def __init__(self, examples: dict[str, list[str]], *, temperature: float = 0.008, top_k: int = 3) -> None:
        self.examples = {k: v for k, v in examples.items() if v}
        self.temperature = temperature
        self.top_k = top_k
        self._matrix: np.ndarray | None = None
        self._owner: np.ndarray | None = None
        self.labels: list[str] = list(self.examples)

    @property
    def fitted(self) -> bool:
        return self._matrix is not None

    def fit(self, embedder: Embedder) -> None:
        texts, owner = [], []
        for idx, label in enumerate(self.labels):
            for text in self.examples[label]:
                texts.append(text)
                owner.append(idx)
        self._matrix = embedder.embed(texts) if texts else np.zeros((0, 1), np.float32)
        self._owner = np.array(owner, dtype=np.int64)

    def predict_vec(self, vec: np.ndarray, *, allowed: set[str] | None = None) -> Prediction:
        if self._matrix is None or self._owner is None:
            raise RuntimeError("siniflandirici egitilmedi (fit)")
        sims = self._matrix @ vec
        labels, scores = [], []
        for idx, label in enumerate(self.labels):
            if allowed is not None and label not in allowed:
                continue
            own = np.sort(sims[self._owner == idx])[::-1][: self.top_k]
            if own.size:
                labels.append(label)
                scores.append(float(own.mean()))
        if not labels:
            raise ValueError("aday sinif yok")
        order = np.argsort(scores)[::-1]
        top = [(labels[i], float(scores[i])) for i in order[:3]]   # ham benzerlikler
        if len(top) == 1:
            confidence = 1.0
        else:  # en iyi iki aday arasindaki fark -> "bu ikisi arasinda ne kadar eminim"
            margin = top[0][1] - top[1][1]
            confidence = float(1.0 / (1.0 + np.exp(-margin / max(self.temperature, 1e-6))))
        return Prediction(label=top[0][0], confidence=confidence, scores=top, method="prototype")


class TrainedHead:
    """Logistic regression (scripts/router_retrain.py ciktisi).

    Model pickle ile DEGIL, yalnizca sayi dizileriyle saklanir (coef, intercept, classes):
    yuklerken kod calistirma riski yoktur. Olasilik burada hesaplanir (sklearn gerekmez).
    """

    def __init__(self, coef: np.ndarray, intercept: np.ndarray, classes: list[str]) -> None:
        self.coef = np.asarray(coef, dtype=np.float64)
        self.intercept = np.asarray(intercept, dtype=np.float64)
        self.labels = [str(c) for c in classes]

    def proba(self, vec: np.ndarray) -> np.ndarray:
        logits = self.coef @ vec.astype(np.float64) + self.intercept
        if len(self.labels) == 2 and logits.shape[0] == 1:   # ikili: tek dogru
            p1 = 1.0 / (1.0 + np.exp(-logits[0]))
            return np.array([1.0 - p1, p1])
        return _softmax(logits, 1.0)

    def predict_vec(self, vec: np.ndarray, *, allowed: set[str] | None = None) -> Prediction:
        probs = self.proba(vec)
        if allowed is not None:
            mask = np.array([lab in allowed for lab in self.labels])
            if not mask.any():
                raise ValueError("aday sinif yok")
            probs = np.where(mask, probs, 0.0)
            probs = probs / probs.sum() if probs.sum() else probs
        order = np.argsort(probs)[::-1]
        top = [(self.labels[i], float(probs[i])) for i in order[:3]]
        return Prediction(label=top[0][0], confidence=top[0][1], scores=top, method="trained")


def save_trained(path: Path | str, heads: dict[str, Any]) -> None:
    """{bas: sklearn LogisticRegression} -> .npz (yalnizca sayisal diziler + sinif adlari)."""
    arrays: dict[str, np.ndarray] = {}
    for head, model in heads.items():
        arrays[f"{head}__coef"] = np.asarray(model.coef_, dtype=np.float64)
        arrays[f"{head}__intercept"] = np.asarray(model.intercept_, dtype=np.float64)
        arrays[f"{head}__classes"] = np.asarray([str(c) for c in model.classes_], dtype=np.str_)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **arrays)


def load_trained(path: Path | str | None) -> dict[str, TrainedHead]:
    """data/router_model.npz -> {"task_types": head, "difficulty": head, "agents": head}."""
    if not path or not Path(path).exists():
        return {}
    try:
        with np.load(path, allow_pickle=False) as data:
            names = sorted({k.split("__")[0] for k in data.files})
            heads = {
                n: TrainedHead(data[f"{n}__coef"], data[f"{n}__intercept"],
                               [str(c) for c in data[f"{n}__classes"]])
                for n in names
            }
        logger.info(f"[router] Egitilmis siniflandirici yuklendi: {', '.join(heads)} ({path})")
        return heads
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[router] Egitilmis model okunamadi, prototip yontemi kullanilacak: {exc!r}")
        return {}


class TaskClassifier:
    """Gorev tipi + zorluk + ajan basliklarini tek gommeyle tahmin eder."""

    def __init__(self, embedder: Embedder, examples: dict[str, dict[str, list[str]]], *,
                 temperature: float = 0.008, trained: dict[str, TrainedHead] | None = None) -> None:
        self.embedder = embedder
        self.heads: dict[str, PrototypeClassifier] = {
            head: PrototypeClassifier(table, temperature=temperature)
            for head, table in examples.items() if table
        }
        self.trained = trained or {}

    @property
    def ready(self) -> bool:
        return bool(self.embedder.ready) and all(h.fitted for h in self.heads.values())

    def fit(self) -> None:
        for head in self.heads.values():
            head.fit(self.embedder)

    def add_agent_examples(self, extra: dict[str, list[str]]) -> None:
        """Ajan prototiplerine ajan basligi/aciklamasini ekler (fit oncesi)."""
        table = self.heads.get("agents")
        merged = {k: list(v) for k, v in (table.examples.items() if table else [])}
        for name, texts in extra.items():
            merged.setdefault(name, [])
            merged[name] += [t for t in texts if t]
        temperature = table.temperature if table else 0.008
        self.heads["agents"] = PrototypeClassifier(merged, temperature=temperature)

    def embed(self, text: str) -> np.ndarray:
        return self.embedder.embed([text])[0]

    def predict(self, head: str, vec: np.ndarray, *, allowed: set[str] | None = None) -> Prediction:
        trained = self.trained.get(head)
        if trained is not None:
            try:
                return trained.predict_vec(vec, allowed=allowed)
            except ValueError:
                pass
        return self.heads[head].predict_vec(vec, allowed=allowed)
