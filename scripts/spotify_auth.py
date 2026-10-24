"""Spotify OAuth yetkilendirmesi (bir kez calistirilir).

    python scripts/spotify_auth.py

On kosul: developer.spotify.com/dashboard'da bir uygulama (Redirect URI:
http://127.0.0.1:8888/callback) ve .env'de SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET.
Tarayicida izin verdikten sonra token SPOTIFY_TOKEN_FILE'a (varsayilan
data/spotify_token.json) yazilir ve CYRAEN spotify_* araclari calismaya baslar.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import spotify_tool  # noqa: E402


def main() -> int:
    try:
        token = spotify_tool.authorize_interactive()
    except RuntimeError as exc:
        print(f"HATA: {exc}")
        return 1
    print(f"Yetkilendirme tamam -> {token}")
    devices = spotify_tool.spotify_devices()
    print("Cihazlar:", devices)
    print("Su an calan:", spotify_tool.spotify_now_playing())
    return 0 if "error" not in devices else 1


if __name__ == "__main__":
    sys.exit(main())
