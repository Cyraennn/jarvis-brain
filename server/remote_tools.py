"""Istemcide calismasi gereken araclari sunucuda VEKIL (proxy) fonksiyonlarla degistirir.

Mevcut kod degismez: `tools/tool_runner.py` ve `agents/agent_tools.py` modullerinin
isim alanindaki fonksiyon referanslari, ayni imza/dokumantasyona sahip vekillerle
degistirilir. Boylece:

  - `ToolRunner._tool_kill_process` gibi ONAYLI araclarda onay SUNUCUDA alinir (mevcut
    `_confirm` akisi), ardindan asil islem (`kill_process`) istemciye `action_request`
    olarak gider. Onay verilmezse istemciye hicbir sey gonderilmez.
  - Ajanlarin yetenek listeleri (`CAPABILITIES`) ayni vekilleri kullanir; Gemini'ye giden
    fonksiyon semalari degismez (`functools.wraps` -> ayni imza).
  - Bagli istemci yoksa arac `{"error": "... bagli istemci yok ..."}` doner (model bunu
    kullaniciya soyler); sunucu islemi KENDISI yapmaya CALISMAZ.

`install()` BrainEngine / ToolRunner OLUSTURULMADAN once cagrilmalidir (ToolRunner kayit
sirasinda fonksiyon referanslarini yakalar).
"""

from __future__ import annotations

import functools
import inspect
from types import ModuleType
from typing import Any, Callable

from loguru import logger

from remote.protocol import CLIENT_FUNCTIONS, action_timeout, qualified_name
from server.hub import ClientHub

_INSTALLED: dict[str, Callable[..., Any]] = {}
_RESTORE: list[tuple[Any, str, Any]] = []            # (modul, ad, orijinal) - uninstall icin
_CAPS_BACKUP: dict[str, list[Callable[..., Any]]] = {}


def make_proxy(fn: Callable[..., Any], hub: ClientHub) -> Callable[..., Any]:
    action = qualified_name(fn)
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def proxy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            bound = sig.bind(*args, **kwargs)
        except TypeError as exc:
            return {"error": f"Gecersiz argumanlar: {exc}"}
        return hub.request_action_blocking(action, dict(bound.arguments), action_timeout(action))

    proxy.__cyraen_remote__ = action  # type: ignore[attr-defined]
    return proxy


def _patch_module(module: ModuleType, hub: ClientHub, originals: dict[int, Callable]) -> list[str]:
    patched: list[str] = []
    for attr, value in list(vars(module).items()):
        if not callable(value) or getattr(value, "__cyraen_remote__", None):
            continue
        name = qualified_name(value)
        if name not in CLIENT_FUNCTIONS:
            continue
        proxy = _INSTALLED.get(name) or make_proxy(value, hub)
        _INSTALLED[name] = proxy
        originals[id(value)] = proxy
        _RESTORE.append((module, attr, value))
        setattr(module, attr, proxy)
        patched.append(f"{module.__name__}.{attr}")
    return patched


def install(hub: ClientHub) -> list[str]:
    """Vekilleri kurar; degistirilen isimlerin listesini doner (log/test icin)."""
    import agents.agent_tools as agent_tools
    import tools.tool_runner as tool_runner

    originals: dict[int, Callable] = {}
    patched = _patch_module(tool_runner, hub, originals)
    patched += _patch_module(agent_tools, hub, originals)

    # ajan yetenek listeleri import aninda fonksiyon nesnelerini yakaladi -> onlari da degistir
    for cap, fns in agent_tools.CAPABILITIES.items():
        _CAPS_BACKUP.setdefault(cap, list(fns))
        agent_tools.CAPABILITIES[cap] = [
            originals.get(id(fn)) or _INSTALLED.get(qualified_name(fn)) or fn for fn in fns
        ]

    logger.info(f"Istemci eylem vekilleri kuruldu: {len(patched)} referans "
                f"({len(_INSTALLED)} benzersiz eylem)")
    return patched


def remote_action_names() -> list[str]:
    return sorted(_INSTALLED)


def uninstall() -> None:
    """Vekilleri kaldirir, orijinal fonksiyonlari geri koyar (testler icin)."""
    import agents.agent_tools as agent_tools

    while _RESTORE:
        module, attr, original = _RESTORE.pop()
        setattr(module, attr, original)
    for cap, fns in _CAPS_BACKUP.items():
        agent_tools.CAPABILITIES[cap] = fns
    _CAPS_BACKUP.clear()
    _INSTALLED.clear()
