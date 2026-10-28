"""Konusmaci dogrulama ("yalniz benim sesim") - yerel ses izi karsilastirmasi.

`scripts/voice_enroll.py` kullanicinin sesinden bir profil (gomme vektoru) cikarir. Calisirken
uyandirma kapisi (`BrainEngine._gate_audio`) bu profili iki yerde kullanir:
  - "Hey JARVIS" duyuldugunda son ~1.5 sn ses profille eslesmiyorsa kapi ACILMAZ;
  - kapi acikken pencereyi yalniz eslesen konusma uzatir, art arda eslesmeyen dilimler kapiyi
    kapatir (`SpeakerGate`).
Ses buluta gitmeden once, yerelde (sherpa-onnx + WeSpeaker ONNX modeli) degerlendirilir.

Paket, model ya da profil yoksa `available=False` olur ve kapi eskisi gibi (konusmaci ayirt
etmeden) calisir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

DEFAULT_THRESHOLD = 0.6
MIN_THRESHOLD = 0.45
MAX_THRESHOLD = 0.8
MIN_SAMPLES = 8_000  # 0.5 sn'den kisa ses guvenilir bir iz vermez


def suggest_threshold(own: list[float], others: list[float]) -> tuple[float, str]:
    """(onerilen esik, aciklama). `own`: kendi kliplerinin (biri disarida) skoru; `others`:
    profille eslesmemesi gereken seslerin (ortam, baska konusmaci) skoru."""
    if not own:
        return DEFAULT_THRESHOLD, "UYARI: yeterli ses kaydi yok; varsayilan esik."
    weakest = min(own)
    ceiling = max(others, default=0.0)
    if ceiling >= weakest:
        return (round(min(MAX_THRESHOLD, max(MIN_THRESHOLD, weakest)), 2),
                f"UYARI: sesin ortamdan net ayrismiyor (en zayif klip {weakest:.2f}, "
                f"ortam {ceiling:.2f}); daha sessiz bir ortamda yeniden kaydet.")
    # kendi en zayif klibinin biraz altinda, ortam tepesinin ustunde kal
    value = max((weakest + ceiling) / 2, weakest - 0.12)
    value = round(min(MAX_THRESHOLD, max(MIN_THRESHOLD, value)), 2)
    return value, f"Kendi kliplerin {weakest:.2f}-{max(own):.2f}, ortam en fazla {ceiling:.2f}."


def save_profile(path: Path, embeddings: list[np.ndarray], threshold: float) -> None:
    mean = np.mean(np.stack(embeddings), axis=0)
    mean = mean / (np.linalg.norm(mean) or 1.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, embedding=mean.astype(np.float32), threshold=np.float32(threshold),
             clips=np.int32(len(embeddings)))


class SpeakerVerifier:
    """16 kHz int16 PCM -> kayitli profille kosinus benzerligi (0-1 civari; yuksek = ayni kisi)."""

    def __init__(
        self, model_path: Path | str, profile_path: Path | str,
        threshold: float = 0.0, sample_rate: int = 16_000,
    ) -> None:
        self.model_path = Path(model_path)
        self.profile_path = Path(profile_path)
        self._threshold_override = float(threshold or 0.0)
        self.threshold = self._threshold_override or DEFAULT_THRESHOLD
        self.sample_rate = sample_rate
        self._extractor: Any = None
        self._profile: np.ndarray | None = None
        self.available: bool | None = None  # None = henuz denenmedi

    def load_model(self) -> bool:
        """Yalniz gomme modelini yukler (kayit betigi profil olmadan da kullanir)."""
        if self._extractor is not None:
            return True
        if not self.model_path.is_file():
            logger.debug(f"Ses izi modeli yok: {self.model_path}")
            return False
        try:
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.model_path), num_threads=2
            )
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Ses izi modeli yuklenemedi: {exc!r}")
            return False

    def load(self) -> bool:
        if self.available is not None:
            return self.available
        self.available = False
        if not self.profile_path.is_file():
            logger.info("Ses profili yok; konusmaci dogrulama pasif "
                        "(olusturmak icin: python scripts/voice_enroll.py).")
            return False
        if not self.load_model():
            return False
        try:
            with np.load(self.profile_path) as data:
                self._profile = np.asarray(data["embedding"], dtype=np.float32)
                stored = float(data["threshold"]) if "threshold" in data else 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Ses profili okunamadi: {exc!r}")
            return False
        self.threshold = self._threshold_override or stored or DEFAULT_THRESHOLD
        self.available = True
        logger.success(f"Konusmaci dogrulama hazir (esik {self.threshold:.2f}).")
        return True

    def embed(self, pcm: bytes) -> np.ndarray | None:
        """Birim uzunlukta gomme vektoru; ses cok kisaysa / model yoksa None."""
        if self._extractor is None:
            return None
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size < MIN_SAMPLES:
            return None
        stream = self._extractor.create_stream()
        stream.accept_waveform(self.sample_rate, samples)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            return None
        vector = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else None

    def score(self, pcm: bytes) -> float:
        """Profille benzerlik; degerlendirilemiyorsa 0.0."""
        if not self.available or self._profile is None:
            return 0.0
        vector = self.embed(pcm)
        return float(vector @ self._profile) if vector is not None else 0.0


class SpeakerGate:
    """Saf durum makinesi: sesli parcalari sabit dilimlerde biriktirir, kararlari sayar.

    `add` bir dilim dolunca onu dondurur (cagiran dogrular); `record(matched)` True donerse
    art arda `max_misses` dilim eslesmemistir ve kapi kapatilmalidir.
    """

    def __init__(self, segment_bytes: int, max_misses: int = 2) -> None:
        self.segment_bytes = int(segment_bytes)
        self.max_misses = int(max_misses)
        self._buf = bytearray()
        self.misses = 0

    def add(self, pcm: bytes) -> bytes | None:
        self._buf += pcm
        if len(self._buf) < self.segment_bytes:
            return None
        segment = bytes(self._buf)
        self._buf.clear()
        return segment

    def record(self, matched: bool) -> bool:
        self.misses = 0 if matched else self.misses + 1
        return self.misses >= self.max_misses

    def reset(self) -> None:
        self._buf.clear()
        self.misses = 0


def build_speaker_verifier(settings: Any) -> SpeakerVerifier:
    return SpeakerVerifier(
        settings.speaker_model_path, settings.speaker_profile_path,
        threshold=settings.speaker_threshold, sample_rate=settings.audio.send_sample_rate,
    )
