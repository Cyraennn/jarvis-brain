"""Kisisel hafiza aramasi - kullanicinin TUM Obsidian kasalarinda anlamsal arama.

Kodu kopyalamaz: kullanicinin mevcut `obsidian-search/search.py` aracini (multilingual-e5-small,
yerel ONNX) importlib ile yukler; boylece Claude Code ve JARVIS AYNI indeksi paylasir.

- Indeks artimli guncellenir, en fazla `_UPDATE_EVERY_S` saniyede bir.
- Ayni indeksi Claude Code da yazabildigi icin guncelleme `index/.lock` dosya kilidiyle yapilir;
  kilit alinamazsa guncelleme atlanir ve mevcut indeksle aranir.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

from loguru import logger

_UPDATE_EVERY_S = 60.0
_SNIPPET_CHARS = 600

_state_lock = threading.Lock()
_module: ModuleType | None = None
_embedder_box: list[Any] = [None]
_last_update = 0.0


def search_dir() -> Path:
    raw = os.getenv("JARVIS_VAULT_SEARCH_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".claude" / "tools" / "obsidian-search"


def _load_module() -> ModuleType:
    global _module
    if _module is None:
        path = search_dir() / "search.py"
        if not path.is_file():
            raise FileNotFoundError(f"Kasa arama araci bulunamadi: {path}")
        spec = importlib.util.spec_from_file_location("jarvis_obsidian_search", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Yuklenemedi: {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _module = mod
    return _module


@contextlib.contextmanager
def _index_lock(index_dir: Path) -> Iterator[bool]:
    """Surecler arasi kilit (Windows: msvcrt). Alinamazsa False verir, beklemez."""
    index_dir.mkdir(parents=True, exist_ok=True)
    handle = open(index_dir / ".lock", "a+b")  # noqa: SIM115
    locked = False
    try:
        try:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        except ImportError:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                locked = False
        except OSError:
            locked = False
        yield locked
    finally:
        if locked:
            with contextlib.suppress(Exception):
                try:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except ImportError:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _fresh_index(mod: ModuleType) -> tuple[dict[str, Any], Any]:
    """Gerekiyorsa indeksi artimli gunceller, sonra (meta, vektorler) doner."""
    global _last_update
    if time.monotonic() - _last_update >= _UPDATE_EVERY_S or _last_update == 0.0:
        with _index_lock(Path(mod.INDEX_DIR)) as locked:
            if locked:
                try:
                    _, _, changed = mod.update_index(_embedder_box)
                    if changed:
                        logger.info(f"Kasa indeksi guncellendi ({changed} not).")
                except Exception as exc:  # noqa: BLE001 - arama yine eski indeksle calisir
                    logger.warning(f"Kasa indeksi guncellenemedi: {exc!r}")
                _last_update = time.monotonic()
            else:
                logger.debug("Kasa indeksi baska bir surecte kilitli; mevcut indeksle araniyor.")
    return mod.load_index()


def memory_search(query: str, vault: str = "", k: int = 6) -> dict[str, Any]:
    """Kullanicinin Obsidian kasalarinda (notlar, okul, JARVIS konusmalari/hafizasi) anlamsal arama."""
    query = (query or "").strip()
    if not query:
        return {"error": "'query' bos olamaz."}
    k = max(1, min(int(k or 6), 15))
    try:
        with _state_lock:
            mod = _load_module()
            meta, vecs = _fresh_index(mod)
            if not meta.get("chunks"):
                return {"query": query, "count": 0, "results": [], "note": "indeks bos"}
            if _embedder_box[0] is None:
                _embedder_box[0] = mod.Embedder()
            q = _embedder_box[0].embed([f"query: {query}"])[0]
    except (FileNotFoundError, ImportError, ModuleNotFoundError) as exc:
        return {"error": f"Kisisel hafiza aramasi kullanilamiyor: {exc}"}

    scores = vecs @ q
    want = vault.strip().lower()
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for i in (-scores).argsort():
        c = meta["chunks"][int(i)]
        if want and c["vault"].lower() != want:
            continue
        key = (c["key"], c["heading"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "vault": c["vault"],
            "note": c["rel"],
            "heading": c["heading"],
            "text": " ".join(c["text"].split())[:_SNIPPET_CHARS],
            "path": c["path"],
            "score": round(float(scores[int(i)]), 3),
        })
        if len(results) >= k:
            break
    return {"query": query, "count": len(results), "results": results,
            "vaults": sorted({c["vault"] for c in meta["chunks"]})}
