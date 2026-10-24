"""Canli ses icin gercek zamanli efektler (24 kHz, 16-bit mono PCM).

UltronFx, Gemini'nin derin hazir sesini Age of Ultron'daki gibi metalik, cift katmanli
ve hafif "makine" tinili bir sese cevirir:
  1. ring modulasyonu (dusuk frekansli tasiyici) -> robotik vizilti
  2. geri beslemeli kisa tarak filtresi -> zirh/metal rezonansi
  3. gecikmeli ikinci katman -> cift ses (filmdeki katmanli tini)
  4. yumusak kirpma + hafif alcak geciren -> sertlik, tizler kulak tirmalamaz

Durumludur (faz ve gecmis tamponlari parcalar arasinda tasinir), boylece parca
sinirlarinda tikirti olmaz. Cikti uzunlugu girdiyle aynidir; _play_audio'daki eko
zamanlamasi bu uzunluga dayanir.
"""

from __future__ import annotations

import numpy as np


class UltronFx:
    def __init__(
        self,
        sample_rate: int = 24_000,
        ring_hz: float = 55.0,
        ring_mix: float = 0.35,
        comb_ms: float = 5.5,
        comb_feedback: float = 0.42,
        double_ms: float = 11.0,
        double_mix: float = 0.3,
        drive: float = 1.4,
        out_gain: float = 0.62,
    ) -> None:
        self.sr = sample_rate
        self.ring_step = 2.0 * np.pi * ring_hz / sample_rate
        self.ring_mix = ring_mix
        self.comb_d = max(1, int(sample_rate * comb_ms / 1000))
        self.comb_g = comb_feedback
        self.double_d = max(1, int(sample_rate * double_ms / 1000))
        self.double_mix = double_mix
        self.drive = drive
        self.out_gain = out_gain
        self.reset()

    def reset(self) -> None:
        self._phase = 0.0
        self._comb_hist = np.zeros(self.comb_d, dtype=np.float32)  # son D cikti
        self._double_hist = np.zeros(self.double_d, dtype=np.float32)  # son D girdi
        self._lp_hist = np.zeros(2, dtype=np.float32)

    def process(self, chunk: bytes) -> bytes:
        if len(chunk) < 2:
            return chunk
        tail = chunk[len(chunk) - len(chunk) % 2 :]  # tek bayt kalirsa aynen geri ekle
        x = np.frombuffer(chunk[: len(chunk) - len(tail)], dtype="<i2").astype(np.float32)
        x /= 32768.0
        n = x.size

        # 1) ring modulasyonu
        phases = self._phase + self.ring_step * np.arange(n, dtype=np.float64)
        self._phase = float((self._phase + self.ring_step * n) % (2.0 * np.pi))
        y = (1.0 - self.ring_mix) * x + self.ring_mix * x * np.sin(phases).astype(np.float32)

        # 2) geri beslemeli tarak: out[i] = y[i] + g * out[i-D]; D'lik bloklarla vektorel
        d = self.comb_d
        out = np.concatenate([self._comb_hist, np.empty(n, dtype=np.float32)])
        for start in range(0, n, d):
            stop = min(start + d, n)
            out[d + start : d + stop] = y[start:stop] + self.comb_g * out[start:stop]
        self._comb_hist = out[-d:].copy()
        y = out[d:] * (1.0 - self.comb_g)

        # 3) gecikmeli ikinci katman (girdinin D2 ornek oncesi)
        dd = self.double_d
        src = np.concatenate([self._double_hist, x])
        self._double_hist = src[-dd:].copy()
        y = y + self.double_mix * src[:n]

        # 4) yumusak kirpma + 3 vuruslu alcak geciren
        y = np.tanh(self.drive * y) / np.tanh(self.drive)
        padded = np.concatenate([self._lp_hist, y.astype(np.float32)])
        self._lp_hist = padded[-2:].copy()
        y = 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]

        y = np.clip(y * self.out_gain * 32767.0, -32768, 32767).astype("<i2")
        return y.tobytes() + tail


def make(effect: str, sample_rate: int = 24_000) -> UltronFx | None:
    """Kisilik efekt adindan islemci; bilinmeyen/bos ad -> None (efektsiz)."""
    if effect == "ultron":
        return UltronFx(sample_rate)
    return None
