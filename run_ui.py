"""JARVIS masaustu arayuzunu baslatir.

Kullanim:
    python run_ui.py

Sessiz (arayuzsuz) mod icin: python main.py
"""

from __future__ import annotations

import sys

from ui.app import run

if __name__ == "__main__":
    sys.exit(run())
