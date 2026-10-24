"""El Kontrolu modellerini yerel olarak indirir (cevrimdisi kullanim icin bir kez calistirin).

    python scripts/el_modeli_indir.py

Indirilenler `web/static/models/` altina gider ve /models/<dosya> ile sunulur:
  - MediaPipe tasks-vision 0.10.14 ESM paketi + wasm (SIMD ve SIMD'siz)
  - El takip modeli (hand_landmarker.task, ~7,5 MB)
  - Yuz algilama modeli (blaze_face_short_range.tflite, ~0,2 MB)
Varsa atlanir; --yeniden ile hepsi tekrar indirilir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

VER = "0.10.14"
CDN = f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{VER}"
FILES = {
    "vision_bundle.mjs": f"{CDN}/vision_bundle.mjs",
    "vision_wasm_internal.js": f"{CDN}/wasm/vision_wasm_internal.js",
    "vision_wasm_internal.wasm": f"{CDN}/wasm/vision_wasm_internal.wasm",
    "vision_wasm_nosimd_internal.js": f"{CDN}/wasm/vision_wasm_nosimd_internal.js",
    "vision_wasm_nosimd_internal.wasm": f"{CDN}/wasm/vision_wasm_nosimd_internal.wasm",
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                            "hand_landmarker/float16/1/hand_landmarker.task",
    "blaze_face_short_range.tflite": "https://storage.googleapis.com/mediapipe-models/face_detector/"
                                     "blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
}
OUT = Path(__file__).resolve().parent.parent / "web" / "static" / "models"


def main(argv: list[str]) -> int:
    force = "--yeniden" in argv
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for name, url in FILES.items():
            target = OUT / name
            if target.is_file() and target.stat().st_size > 0 and not force:
                print(f"  var   {name}")
                continue
            try:
                r = client.get(url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"  HATA  {name}: {exc}")
                failed += 1
                continue
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.replace(target)
            print(f"  indi  {name} ({len(r.content) / 1e6:.1f} MB)")
    print("Tamam." if not failed else f"{failed} dosya indirilemedi.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
