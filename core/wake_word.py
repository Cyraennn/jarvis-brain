"""Uyandirma kelimesi ("Hey JARVIS") - cevrimdisi openWakeWord + uyku/uyaniklik kapisi.

Kapi etkinken mikrofon sesi UYKUDA Gemini Live'a GONDERILMEZ; yalnizca yerel detektore verilir.
"Hey JARVIS" duyulunca `wake_window_s` saniye boyunca ses normal akar; kullanici konustukca,
model konustukca veya arac calistikca pencere uzar. Sessizlikte tekrar uykuya gecer.

openwakeword kurulu degilse / model yuklenemezse detektor `available=False` olur ve motor
kapisiz (her zaman dinleyen) eski davranisla devam eder.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

import numpy as np
from loguru import logger

FRAME_SAMPLES = 1280  # openWakeWord: 80 ms @ 16 kHz


class WakeWordDetector:
    """16 kHz int16 PCM parcalarini 80 ms'lik karelere boler ve wake-word skoru uretir."""

    def __init__(self, model_name: str = "hey_jarvis") -> None:
        self.model_name = model_name
        self._model: object | None = None
        self._buf = np.zeros(0, dtype=np.int16)
        self.available: bool | None = None  # None = henuz denenmedi

    def load(self) -> bool:
        if self.available is not None:
            return self.available
        try:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            download_models(model_names=[self.model_name])  # yalniz ilk seferde indirir
            self._model = Model(wakeword_models=[self.model_name], inference_framework="onnx")
            self.available = True
            logger.success(f"Uyandirma kelimesi hazir: '{self.model_name}'.")
        except Exception as exc:  # noqa: BLE001 - kapisiz moda dus
            self.available = False
            logger.warning(f"Uyandirma kelimesi yuklenemedi ({exc!r}); mikrofon kapisiz calisacak.")
        return self.available

    def score(self, pcm: bytes) -> float:
        """Bu parca ile tamamlanan karelerin en yuksek skoru (0-1)."""
        if not self.available or self._model is None:
            return 0.0
        self._buf = np.concatenate([self._buf, np.frombuffer(pcm, dtype=np.int16)])
        best = 0.0
        while self._buf.size >= FRAME_SAMPLES:
            frame, self._buf = self._buf[:FRAME_SAMPLES], self._buf[FRAME_SAMPLES:]
            scores = self._model.predict(frame)  # type: ignore[attr-defined]
            best = max(best, float(scores.get(self.model_name, 0.0)))
        return best

    def reset(self) -> None:
        """Uyanistan sonra ic tamponlari temizle (ayni cumle tekrar tetiklemesin)."""
        self._buf = np.zeros(0, dtype=np.int16)
        if self._model is not None:
            try:
                self._model.reset()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass


class WakeGate:
    """Saf uyku/uyaniklik durum makinesi (ses/ag bagimsiz, test edilebilir)."""

    def __init__(
        self,
        window_s: float = 8.0,
        preroll_chunks: int = 8,
        clock: Callable[[], float] = time.monotonic,
        max_awake_s: float = 0.0,
    ) -> None:
        self.window_s = float(window_s)
        # Tek uyanisla en fazla bu kadar uyanik kalinir (0 = sinirsiz): ortamdaki surekli
        # konusma `touch()` ile pencereyi sonsuza kadar acik tutamaz.
        self.max_awake_s = float(max_awake_s)
        self._clock = clock
        self._awake_since = 0.0
        self._awake_until = 0.0
        self._preroll: deque[bytes] = deque(maxlen=max(0, preroll_chunks))
        self._reported_awake = False

    @property
    def awake(self) -> bool:
        return self._clock() < self._awake_until

    def wake(self) -> list[bytes]:
        """Uyandir; uyurken biriken on-dolum parcalarini (cumlenin basi) dondurur."""
        self._awake_since = self._clock()
        self._extend()
        chunks = list(self._preroll)
        self._preroll.clear()
        return chunks

    def touch(self) -> None:
        """Uyaniksa pencereyi uzatir (konusma, model yaniti, arac cagrisi)."""
        if self.awake:
            self._extend()

    def keep_awake(self, fresh: bool = True) -> None:
        """Uykuda olsa bile pencereyi ac (model konusuyor: kullanici cevap verebilsin).

        fresh=True yeni bir uyanis sayilir (hatirlatici / ajan sonucu okundu). fresh=False
        yalnizca son uyanisin `max_awake_s` tavani dolmadiysa acar: mikrofondan duyulana
        verilen yanitlar tavani sifirlayamaz, yoksa ortam sohbeti kendi kendini beslerdi.
        """
        if not self.awake:
            capped = self.max_awake_s > 0 and self._clock() >= self._awake_since + self.max_awake_s
            if not fresh and capped:
                return
            if fresh:
                self._awake_since = self._clock()
        self._extend()

    def _extend(self) -> None:
        until = self._clock() + self.window_s
        if self.max_awake_s > 0:
            until = min(until, self._awake_since + self.max_awake_s)
        self._awake_until = until

    def sleep(self) -> None:
        self._awake_until = 0.0

    def remember(self, chunk: bytes) -> None:
        """Uykudayken son parcalari tut (uyaninca gonderilecek on-dolum)."""
        self._preroll.append(chunk)

    def transition(self) -> bool | None:
        """Son cagridan beri durum degistiyse yeni durumu (True=uyanik), degismediyse None."""
        now_awake = self.awake
        if now_awake == self._reported_awake:
            return None
        self._reported_awake = now_awake
        return now_awake
