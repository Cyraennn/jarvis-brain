"""Dosya/klasor islemleri - tasi, kopyala, yeniden adlandir, klasor olustur, zip, ara.

Uzerine yazma ve silme riskli islemler ToolRunner tarafindan onay kapisina baglanir.
"""

from __future__ import annotations

import fnmatch
import shutil
import zipfile
from pathlib import Path
from typing import Any


def _p(path: str) -> Path:
    return Path(path).expanduser()


def move_path(source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    """Bir dosya/klasoru tasir. `overwrite=True` hedefi degistirir."""
    src, dst = _p(source), _p(destination)
    if not src.exists():
        return {"error": f"Kaynak yok: {src}"}
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists() and not overwrite:
        return {"error": f"Hedef zaten var (overwrite ile gecin): {dst}"}
    try:
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(src), str(dst))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Tasima basarisiz: {exc}"}
    return {"status": "tasindi", "from": str(src), "to": str(dst)}


def copy_path(source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    """Bir dosya/klasoru kopyalar."""
    src, dst = _p(source), _p(destination)
    if not src.exists():
        return {"error": f"Kaynak yok: {src}"}
    if dst.is_dir() and src.is_file():
        dst = dst / src.name
    if dst.exists() and not overwrite:
        return {"error": f"Hedef zaten var: {dst}"}
    try:
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=overwrite)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Kopyalama basarisiz: {exc}"}
    return {"status": "kopyalandi", "from": str(src), "to": str(dst)}


def rename_path(path: str, new_name: str) -> dict[str, Any]:
    """Bir dosya/klasorun adini degistirir (ayni klasorde)."""
    src = _p(path)
    if not src.exists():
        return {"error": f"Yol yok: {src}"}
    dst = src.with_name(new_name.strip())
    if dst.exists():
        return {"error": f"Bu ad zaten var: {dst.name}"}
    try:
        src.rename(dst)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Yeniden adlandirilamadi: {exc}"}
    return {"status": "yeniden adlandirildi", "new_path": str(dst)}


def make_folder(path: str) -> dict[str, Any]:
    """Klasor(ler) olusturur."""
    p = _p(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Olusturulamadi: {exc}"}
    return {"status": "olusturuldu", "path": str(p)}


def zip_paths(sources: str, archive_path: str) -> dict[str, Any]:
    """Bir veya daha fazla yolu (virgulle ayrilmis) zip'e sikistirir."""
    items = [_p(s.strip()) for s in sources.split(",") if s.strip()]
    missing = [str(i) for i in items if not i.exists()]
    if missing:
        return {"error": f"Bulunamayan: {missing}"}
    arc = _p(archive_path)
    if not arc.suffix:
        arc = arc.with_suffix(".zip")
    try:
        arc.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                if it.is_file():
                    zf.write(it, it.name)
                else:
                    for f in it.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(it.parent))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Sikistirilamadi: {exc}"}
    return {"status": "olusturuldu", "archive": str(arc),
            "size_kb": round(arc.stat().st_size / 1024, 1)}


def find_files(pattern: str, in_dir: str = "", limit: int = 50) -> dict[str, Any]:
    """Bir dizinde ada gore dosya arar (glob deseni, orn '*.pdf', 'rapor*')."""
    root = _p(in_dir) if in_dir else Path.home()
    if not root.is_dir():
        return {"error": f"Dizin yok: {root}"}
    pat = pattern.strip() or "*"
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "$RECYCLE.BIN"}
    hits: list[str] = []
    try:
        for f in root.rglob("*"):
            if len(hits) >= limit:
                break
            if any(part in skip for part in f.parts):
                continue
            if f.is_file() and fnmatch.fnmatch(f.name.lower(), pat.lower()):
                hits.append(str(f))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Arama hatasi: {exc}"}
    return {"pattern": pat, "root": str(root), "count": len(hits), "files": hits}
