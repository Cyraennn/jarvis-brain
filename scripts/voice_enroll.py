"""Ses profili kaydi ("yalniz benim sesim") - gercek mikrofonla.

    python scripts/voice_enroll.py            # profil olustur / yenile
    python scripts/voice_enroll.py --check    # canli: konusurken ses izi skorunu goster

CYRAEN KAPALIYKEN calistirin (mikrofonu ayni anda iki surec acamayabilir).
1. Adim: 5 sn ORTAM sesi (konusmayin) -> profille eslesmemesi gereken ses.
2. Adim: ekrandaki cumleleri normal sesinizle okuyun.
3. Adim: birkac kez "Hey CYRAEN" deyin (uyanis kisa bir ifade uzerinden dogrulanir).
Profil `data/voice/profile.npz` dosyasina yazilir; CYRAEN bir sonraki acilista kullanir.
Ses kayitlari SAKLANMAZ, yalnizca sayisal ses izi (256 sayi) kaydedilir.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from core.speaker_verify import build_speaker_verifier, save_profile, suggest_threshold  # noqa: E402

RATE = 16_000
CHUNK = 1_024
MIN_LEVEL = 0.03  # bu seviyenin altindaki klip "konusulmadi" sayilir

SENTENCES = [
    "Bugün hava çok güzel, dışarı çıkıp biraz yürümek istiyorum.",
    "Yarın sabah dokuzda dersim var, bana sekiz buçukta hatırlatır mısın?",
    "Müzik çalar mısın, sonra da sesi biraz kısar mısın lütfen?",
    "Okunmamış e-postalarıma bak ve önemli olanları özetle.",
    "Ekrandaki pencereyi kapatma, sadece küçült ve tarayıcıyı aç.",
    "Bu hafta hangi sınavlarım var ve hangi konulardan sorumluyum?",
]


def leave_one_out(embeddings: list[np.ndarray]) -> list[float]:
    """Her klibin, DIGER kliplerin ortalamasiyla benzerligi (profilin kendine tutarliligi)."""
    scores: list[float] = []
    for i, vector in enumerate(embeddings):
        rest = [e for j, e in enumerate(embeddings) if j != i]
        if not rest:
            continue
        mean = np.mean(np.stack(rest), axis=0)
        scores.append(float(vector @ (mean / (np.linalg.norm(mean) or 1.0))))
    return scores


def _level(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples ** 2)) / 9000.0) if samples.size else 0.0


def _record(stream, seconds: float, label: str) -> bytes:
    out = bytearray()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        chunk = stream.read(CHUNK, exception_on_overflow=False)
        out += chunk
        bar = "#" * min(30, int(_level(chunk) * 60))
        print(f"\r  {label} [{bar:<30}] {end - time.monotonic():4.1f} sn ", end="", flush=True)
    print()
    return bytes(out)


def _clip(stream, verifier, prompt: str, seconds: float, label: str) -> np.ndarray | None:
    """Bir klip kaydeder; konusulmadiysa bir kez daha ister. Gomme vektoru ya da None."""
    for _attempt in range(2):
        input(prompt)
        pcm = _record(stream, seconds, label)
        if _level(pcm) < MIN_LEVEL:
            print("  Ses cok dusuk / konusma duyulmadi; tekrar deneyin.")
            continue
        vector = verifier.embed(pcm)
        if vector is not None:
            return vector
    return None


def _check(stream, verifier) -> int:
    if not verifier.load():
        print("Profil yok ya da yuklenemedi; once profil olusturun.")
        return 1
    print(f"Canli kontrol (esik {verifier.threshold:.2f}). Konusun; cikmak icin Ctrl+C.")
    try:
        while True:
            pcm = _record(stream, 2.0, "dinliyor")
            if _level(pcm) < MIN_LEVEL:
                print("  (sessiz)")
                continue
            score = verifier.score(pcm)
            print(f"  ses izi {score:.2f} -> {'SEN' if score >= verifier.threshold else 'baskasi'}")
    except KeyboardInterrupt:
        print()
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="kayit yapma, canli skor goster")
    ap.add_argument("--wake-tries", type=int, default=5, help="'Hey CYRAEN' tekrar sayisi")
    args = ap.parse_args()

    settings = get_settings()
    verifier = build_speaker_verifier(settings)
    if not verifier.load_model():
        print(f"Ses izi modeli yuklenemedi: {settings.speaker_model_path}\n"
              "(pip install sherpa-onnx ve model dosyasi gerekli)")
        return 1

    import pyaudio

    pya = pyaudio.PyAudio()
    stream = pya.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                      frames_per_buffer=CHUNK)
    try:
        if args.check:
            return _check(stream, verifier)

        print("\n1) 5 sn ORTAM sesi: KONUSMAYIN (TV / muzik aciksa acik kalsin).")
        input("   Hazir olunca Enter...")
        ambient = _record(stream, 5.0, "ortam")

        print("\n2) Cumleleri normal konusma sesinizle, mikrofona her zamanki mesafeden okuyun.")
        own: list[np.ndarray] = []
        for i, sentence in enumerate(SENTENCES, 1):
            vector = _clip(stream, verifier, f"\n   {i}/{len(SENTENCES)}: \"{sentence}\"\n   Enter'a basip okuyun...",
                           6.0, f"cumle {i}")
            if vector is not None:
                own.append(vector)

        print("\n3) Simdi 'Hey CYRAEN' deyin.")
        for i in range(1, args.wake_tries + 1):
            vector = _clip(stream, verifier, f"   {i}/{args.wake_tries}: Enter'a basip 'Hey CYRAEN' deyin...",
                           2.0, f"hey {i}")
            if vector is not None:
                own.append(vector)
    except KeyboardInterrupt:
        print("\nIptal edildi; profil degistirilmedi.")
        return 130
    finally:
        stream.stop_stream()
        stream.close()
        pya.terminate()

    if len(own) < 4:
        print(f"\nYalnizca {len(own)} gecerli klip var; profil olusturulmadi. Tekrar deneyin.")
        return 1

    self_scores = leave_one_out(own)
    mean = np.mean(np.stack(own), axis=0)
    mean /= np.linalg.norm(mean) or 1.0
    ambient_vec = verifier.embed(ambient)
    others = [float(ambient_vec @ mean)] if ambient_vec is not None else []
    threshold, note = suggest_threshold(self_scores, others)
    save_profile(settings.speaker_profile_path, own, threshold)

    print("\n--- SONUC ---")
    print("Kendi kliplerin: " + ", ".join(f"{s:.2f}" for s in self_scores))
    print("Ortam          : " + (", ".join(f"{s:.2f}" for s in others) or "-"))
    print(note)
    print(f"Profil yazildi: {settings.speaker_profile_path} (esik {threshold:.2f}, {len(own)} klip)")
    print("CYRAEN'i yeniden baslatin. Dene: python scripts/voice_enroll.py --check")
    print("Esigi elle degistirmek icin .env: CYRAEN_SPEAKER_THRESHOLD=0.xx · kapatmak icin "
          "CYRAEN_SPEAKER_VERIFY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
