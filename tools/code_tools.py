"""Kod calistirma - Python / shell / git.

Guvenlik: `settings.code_exec_enabled` (varsayilan KAPALI) + ToolRunner onay kapisi.
Calisma dizini data/sandbox/, cikti yakalanir, timeout uygulanir.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from config.settings import APP_DIR, BASE_DIR, get_settings

_SANDBOX = APP_DIR / "data" / "sandbox"


def _enabled() -> bool:
    return bool(get_settings().code_exec_enabled)


def _run(cmd: list[str], cwd: Path, timeout: float) -> dict[str, Any]:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, check=False)
        out = (r.stdout or "")[-4000:]
        err = (r.stderr or "")[-2000:]
        return {"exit_code": r.returncode, "stdout": out, "stderr": err}
    except subprocess.TimeoutExpired:
        return {"error": f"zaman asimi ({timeout:.0f}s)"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_python(code: str) -> dict[str, Any]:
    """Bir Python kod parcasini ayri yorumlayicida calistirir (sandbox, timeout). ONAYA TABI."""
    if not _enabled():
        return {"error": "Kod calistirma kapali. .env'e CYRAEN_CODE_EXEC=true ekleyin."}
    if not (code or "").strip():
        return {"error": "kod bos"}
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    script = _SANDBOX / "_run.py"
    script.write_text(code, encoding="utf-8")
    s = get_settings()
    res = _run([sys.executable, "-I", str(script)], _SANDBOX, s.code_exec_timeout)
    return {"language": "python", **res}


def run_shell(command: str) -> dict[str, Any]:
    """Bir kabuk komutu calistirir (PowerShell/Bash). ONAYA TABI."""
    if not _enabled():
        return {"error": "Kod calistirma kapali. .env'e CYRAEN_CODE_EXEC=true ekleyin."}
    cmd = (command or "").strip()
    if not cmd:
        return {"error": "komut bos"}
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    if sys.platform == "win32":
        full = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        full = ["bash", "-lc", cmd]
    return {"command": cmd, **_run(full, _SANDBOX, s.code_exec_timeout)}


_READONLY_GIT = {"status", "log", "diff", "branch", "show", "remote", "config", "ls-files"}


def git_command(subcommand: str, repo: str = "") -> dict[str, Any]:
    """Git komutu calistirir. Salt-okuma (status/log/diff/branch) onaysiz; yazma (add/commit/checkout) ONAYA TABI."""
    parts = (subcommand or "").strip().split()
    if not parts:
        return {"error": "git alt komutu gerekli"}
    root = Path(repo).expanduser() if repo else BASE_DIR
    if not (root / ".git").exists():
        return {"error": f"git deposu degil: {root}"}
    res = _run(["git", *parts], root, 30.0)
    return {"git": " ".join(parts), "repo": str(root), **res}


def git_is_write(subcommand: str) -> bool:
    first = (subcommand or "").strip().split()[:1]
    return bool(first) and first[0] not in _READONLY_GIT
