"""Yerel, internetsiz metin gommesi: multilingual-e5-small (ONNX, quantized).

torch / sentence-transformers gerekmez: onnxruntime + tokenizers yeterli. Model
~/.cache/huggingface altindan okunur (HF_HUB_OFFLINE ile ag denenmez). Ilk yukleme
~4 sn surer -> `load_async` acilista arka planda cagrilir; hazir olana kadar
`ready` False'tur ve router siniflandiriciyi atlar (karara acikca yazilir).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from typing import Protocol

import numpy as np
from loguru import logger

MODEL_REPO = "Xenova/multilingual-e5-small"
DIM = 384
MAX_TOKENS = 128   # yonlendirme icin gorevin basi yeterli; kisa tutmak hizi korur


class Embedder(Protocol):
    @property
    def ready(self) -> bool: ...

    def embed(self, texts: list[str]) -> np.ndarray: ...


class E5Embedder:
    def __init__(self, repo: str = MODEL_REPO) -> None:
        self.repo = repo
        self._sess = None
        self._tok = None
        self._inputs: set[str] = set()
        self._lock = threading.Lock()
        self.error: str | None = None

    @property
    def ready(self) -> bool:
        return self._sess is not None

    def load(self) -> bool:
        with self._lock:
            if self._sess is not None:
                return True
            try:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")  # yalnizca yerel onbellek
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer

                model_path = hf_hub_download(self.repo, "onnx/model_quantized.onnx")
                tok = Tokenizer.from_file(hf_hub_download(self.repo, "tokenizer.json"))
                tok.enable_truncation(MAX_TOKENS)
                tok.enable_padding()
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                sess = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
                self._inputs = {i.name for i in sess.get_inputs()}
                self._tok, self._sess = tok, sess
                logger.success(f"[router] Yerel gomme modeli hazir: {self.repo}")
                return True
            except Exception as exc:  # noqa: BLE001 - router siniflandiricisiz calisir
                self.error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning(
                    f"[router] Yerel gomme modeli YUKLENEMEDI ({self.error}); siniflandirici "
                    "atlanacak, kararlar LLM'e sorulacak."
                )
                return False

    async def load_async(self) -> bool:
        return await asyncio.to_thread(self.load)

    def embed(self, texts: list[str], batch: int = 32) -> np.ndarray:
        if self._sess is None or self._tok is None:
            raise RuntimeError("gomme modeli hazir degil")
        if len(texts) > batch:  # buyuk toplu islem dolgu yuzunden cok yavaslar
            return np.vstack([self.embed(texts[i:i + batch], batch) for i in range(0, len(texts), batch)])
        enc = self._tok.encode_batch([f"query: {t}" for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._sess.run(None, feed)[0]
        m = mask[..., None].astype(np.float32)
        vec = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        return (vec / np.linalg.norm(vec, axis=1, keepdims=True)).astype(np.float32)


class HashingEmbedder:
    """Testler icin deterministik, modelsiz gomme (kelime ozetleri). Uretimde KULLANILMAZ."""

    ready = True

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in (text or "").lower().split():
                word = word.strip(".,!?;:'\"()")
                if not word:
                    continue
                h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
                out[row, h % self.dim] += 1.0
            norm = np.linalg.norm(out[row])
            out[row] = out[row] / norm if norm else out[row]
        return out
