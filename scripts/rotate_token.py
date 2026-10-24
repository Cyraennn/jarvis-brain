"""JARVIS web/telefon erişim anahtarını (JARVIS_WEB_TOKEN) yeniler.

    python scripts/rotate_token.py            # .env'deki token'ı yeni rastgele değerle değiştirir
    python scripts/rotate_token.py --env X    # başka bir .env dosyası

Yeni değer EKRANA YAZILMAZ (sohbet/terminal geçmişine düşmesin). Sonra:
  1. JARVIS'i yeniden başlatın.
  2. Telefonu yeniden eşleyin: PC'de tarayıcıda 127.0.0.1:8770/pair → QR'ı telefonla okutun.
  3. Okul uygulamasında Ayarlar > JARVIS'e yeni token'ı girin (aynı sayfadaki adresten kopyalanabilir).
Eski token anında geçersiz olur (eski adresle gelen istekler 401 alır).
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

KEY = "JARVIS_WEB_TOKEN"
_LINE = re.compile(rf"^(\s*{KEY}\s*=).*$", re.MULTILINE)


def rotate(env_path: Path) -> str:
    """Token satırını değiştirir (yoksa ekler), yeni token'ı döndürür. Diğer satırlara dokunmaz."""
    raw = env_path.read_bytes() if env_path.exists() else b""
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    token = secrets.token_urlsafe(16)
    if _LINE.search(text):
        text = _LINE.sub(lambda m: m.group(1) + token, text, count=1)
    else:
        if text and not text.endswith(("\n", "\r\n")):
            text += newline
        text += f"{KEY}={token}{newline}"
    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(env_path)
    return token


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", type=Path, default=Path(__file__).resolve().parent.parent / ".env")
    args = ap.parse_args(argv)
    token = rotate(args.env)
    print(f"{KEY} yenilendi ({len(token)} karakter) -> {args.env}")
    print("Simdi: JARVIS'i yeniden baslatin, telefonu 127.0.0.1:8770/pair QR'i ile yeniden esleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
