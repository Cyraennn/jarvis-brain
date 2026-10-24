"""PC bakim - disk temizligi icin tarama + onayli, geri alinabilir temizlik.

Ilkeler:
- `cleanup_scan` SALT OKUMA; hicbir seyi silmez.
- Onbellek/gecici klasorler (yeniden olusur) dogrudan silinir; kilitli dosyalar atlanir.
- Kullanici dosyalari (Indirilenler/Masaustu'ndeki buyuk kurulum/arsiv dosyalari) Geri Donusum
  Kutusu'na TASINIR (geri alinabilir). Her calisma `data/maintenance/<tarih>.csv` manifesti yazar.
- Korumali yollar (Windows, Program Files, CYRAEN projesi, Obsidian kasalari) asla aday olmaz.
- Onay kapisi ToolRunner'dadir; bu modul onay istemez.
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import shutil
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import APP_DIR, get_settings

MB = 1024 * 1024
INSTALLER_EXTS = {".exe", ".msi", ".zip", ".rar", ".7z", ".iso"}
TEMP_MIN_AGE_S = 24 * 3600  # calisan kurulumlarin gecici dosyalarina dokunma
SCAN_BUDGET_S = 25.0  # klasor boyutu hesaplama tavani (kategori basina)

# OneDrive "istege bagli dosyalar": bulutta duran dosya yerel diskte yer kaplamaz
_ATTR_OFFLINE = 0x1000
_ATTR_RECALL_ON_DATA_ACCESS = 0x400000
_ATTR_RECALL_ON_OPEN = 0x40000

CATEGORY_LABELS = {
    "temp": "Gecici dosyalar (%TEMP%)",
    "windows_temp": "Windows gecici dosyalari",
    "browser_cache": "Tarayici onbellegi (Opera GX / Edge)",
    "pip_cache": "pip onbellegi",
    "installers": "Buyuk kurulum/arsiv dosyalari (cop kutusuna)",
}
CACHE_CATEGORIES = ("temp", "windows_temp", "browser_cache", "pip_cache")


# ------------------------------------------------------------------ yollar

def _env_path(var: str, *parts: str) -> Path | None:
    base = os.environ.get(var)
    return Path(base, *parts) if base else None


def _known_folder(guid: str) -> Path | None:
    """SHGetKnownFolderPath (Masaustu OneDrive'a yonlendirilmis olabilir)."""
    if sys.platform != "win32":
        return None
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                        ("d4", ctypes.c_ubyte * 8)]

        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(g))
        out = ctypes.c_wchar_p()
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
        path = Path(out.value) if out.value else None
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    except Exception:  # noqa: BLE001
        return None


def cache_roots() -> dict[str, list[Path]]:
    local = os.environ.get("LOCALAPPDATA", "")
    roots: dict[str, list[Path]] = {
        "temp": [p for p in [_env_path("TEMP")] if p],
        "windows_temp": [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"],
        "browser_cache": [
            Path(local, "Opera Software", "Opera GX Stable", "Cache"),
            Path(local, "Opera Software", "Opera GX Stable", "Default", "Cache"),
            Path(local, "Opera Software", "Opera Stable", "Cache"),
            Path(local, "Microsoft", "Edge", "User Data", "Default", "Cache"),
            Path(local, "Google", "Chrome", "User Data", "Default", "Cache"),
        ],
        "pip_cache": [Path(local, "pip", "cache")],
    }
    return {k: [p for p in v if p.is_dir()] for k, v in roots.items()}


def user_file_roots() -> list[Path]:
    home = Path.home()
    found = [
        _known_folder("{374DE290-123F-4565-9164-39C4925E467B}") or home / "Downloads",
        _known_folder("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}") or home / "Desktop",
    ]
    out: list[Path] = []
    for p in found:
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def _protected_roots() -> list[Path]:
    roots = [
        Path(os.environ.get("SystemRoot", r"C:\Windows")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        APP_DIR,
        Path.home() / "Documents",  # Obsidian kasalari burada
    ]
    vault = (get_settings().obsidian_vault or "").strip()
    if vault:
        roots.append(Path(vault))
    return [r.resolve() for r in roots]


def is_protected(path: Path) -> bool:
    try:
        p = path.resolve()
    except OSError:
        return True
    if ".git" in p.parts:
        return True
    for root in _protected_roots():
        if p == root or root in p.parents:
            # Windows\Temp korumali kokun icinde ama bilincli olarak izinli onbellek
            win_temp = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp").resolve()
            if p == win_temp or win_temp in p.parents:
                return False
            return True
    return False


# ------------------------------------------------------------------ olcum

def _is_cloud_only(path: Path) -> bool:
    try:
        attrs = getattr(path.stat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & (_ATTR_OFFLINE | _ATTR_RECALL_ON_DATA_ACCESS | _ATTR_RECALL_ON_OPEN))


def dir_size(root: Path, budget_s: float = SCAN_BUDGET_S, min_age_s: float = 0) -> tuple[int, int, bool]:
    """(bayt, dosya_sayisi, tamamlandi_mi). Sure tavani asilirsa kismi sonuc doner."""
    deadline = time.monotonic() + budget_s
    now = time.time()
    total = count = 0
    stack = [root]
    while stack:
        if time.monotonic() > deadline:
            return total, count, False
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            st = entry.stat(follow_symlinks=False)
                            if min_age_s and now - st.st_mtime < min_age_s:
                                continue
                            total += st.st_size
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count, True


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_info() -> dict[str, Any]:
    if sys.platform != "win32":
        return {"size_mb": 0, "items": 0}
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if hr != 0:
        return {"error": f"Geri Donusum Kutusu okunamadi (hr={hr:#x})"}
    return {"size_mb": round(info.i64Size / MB, 1), "items": int(info.i64NumItems)}


def _drive_usage() -> dict[str, Any]:
    anchor = Path(os.environ.get("SystemDrive", "C:") + "\\")
    u = shutil.disk_usage(anchor)
    return {"drive": str(anchor), "used_percent": round(u.used / u.total * 100, 1),
            "free_gb": round(u.free / 1024**3, 1), "total_gb": round(u.total / 1024**3, 1)}


# ------------------------------------------------------------------ tarama

def _scan_dir() -> Path:
    d = Path(get_settings().data_dir) / "maintenance"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_installers(min_mb: float = 50, older_days: float = 14) -> list[dict[str, Any]]:
    """Indirilenler + Masaustu'nun UST seviyesindeki buyuk ve eski kurulum/arsiv dosyalari."""
    now = time.time()
    out: list[dict[str, Any]] = []
    for root in user_file_roots():
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for p in entries:
            try:
                if not p.is_file() or p.suffix.lower() not in INSTALLER_EXTS or is_protected(p):
                    continue
                st = p.stat()
            except OSError:
                continue
            if st.st_size < min_mb * MB or now - st.st_mtime < older_days * 86400:
                continue
            cloud = _is_cloud_only(p)
            out.append({
                "path": str(p),
                "size_mb": round(st.st_size / MB, 1),
                "age_days": int((now - st.st_mtime) // 86400),
                "cloud_only": cloud,  # bulutta: silmek yerel yer acmaz
            })
    out.sort(key=lambda x: -x["size_mb"])
    for i, item in enumerate(out, 1):
        item["id"] = f"i{i}"
    return out


def cleanup_scan(min_mb: float = 50, older_days: float = 14) -> dict[str, Any]:
    """Diskte guvenle temizlenebilecek yerleri olcer. HICBIR SEY SILMEZ."""
    categories: dict[str, Any] = {}
    for cat, roots in cache_roots().items():
        if not roots:
            continue
        total = files = 0
        complete = True
        for r in roots:
            age = TEMP_MIN_AGE_S if cat in ("temp", "windows_temp") else 0
            b, n, done = dir_size(r, min_age_s=age)
            total, files, complete = total + b, files + n, complete and done
        categories[cat] = {"label": CATEGORY_LABELS[cat], "size_mb": round(total / MB, 1),
                           "files": files, "roots": [str(r) for r in roots],
                           **({} if complete else {"note": "olcum sure siniri nedeniyle kismi"})}

    installers = find_installers(min_mb, older_days)
    local_mb = sum(i["size_mb"] for i in installers if not i["cloud_only"])
    categories["installers"] = {"label": CATEGORY_LABELS["installers"],
                                "size_mb": round(local_mb, 1), "items": installers}
    rb = recycle_bin_info()
    result = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "disk": _drive_usage(),
        "categories": categories,
        "recycle_bin": rb,
        "reclaimable_mb": round(sum(c["size_mb"] for c in categories.values())
                                + float(rb.get("size_mb", 0) or 0), 1),
        "note": ("Hicbir sey silinmedi. Temizlik icin cleanup_run(categories, ids) - onay ister. "
                 "Kurulum dosyalari cop kutusuna gider; cop kutusunu bosaltmak ayri onaylidir."),
    }
    (_scan_dir() / "last_scan.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    return result


def scan_summary(scan: dict[str, Any]) -> str:
    parts = [f"{c['label'].split(' (')[0]} {c['size_mb'] / 1024:.1f} GB"
             for c in scan["categories"].values() if c["size_mb"] >= 100]
    rb = scan.get("recycle_bin", {})
    if (rb.get("size_mb") or 0) >= 100:
        parts.append(f"Cop kutusu {rb['size_mb'] / 1024:.1f} GB")
    total = scan["reclaimable_mb"] / 1024
    return f"~{total:.1f} GB temizlenebilir" + (f" ({', '.join(parts)})" if parts else "")


# ------------------------------------------------------------------ temizlik

def _split(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [v.strip() for v in value if v and v.strip()]


def plan_cleanup(categories: str = "", ids: str = "") -> dict[str, Any]:
    """Neyin temizlenecegini SON TARAMAYA gore cozer (onay onizlemesi icin). Silmez."""
    path = _scan_dir() / "last_scan.json"
    if not path.is_file():
        return {"error": "Once cleanup_scan calistirilmali."}
    scan = json.loads(path.read_text(encoding="utf-8"))
    cats = _split(categories)
    want_ids = set(_split(ids))
    unknown = [c for c in cats if c not in CATEGORY_LABELS]
    if unknown:
        return {"error": f"Bilinmeyen kategori: {', '.join(unknown)}. "
                         f"Gecerli: {', '.join(CATEGORY_LABELS)}"}
    if not cats and not want_ids:
        return {"error": "Kategori (orn. 'temp,browser_cache') veya kurulum dosyasi id'si (orn. 'i1,i3') ver."}

    cache = [c for c in cats if c in CACHE_CATEGORIES and c in scan["categories"]]
    items = scan["categories"].get("installers", {}).get("items", [])
    files = [i for i in items if "installers" in cats or i["id"] in want_ids]
    total = sum(scan["categories"][c]["size_mb"] for c in cache) + sum(
        i["size_mb"] for i in files if not i["cloud_only"])
    return {"cache": cache, "files": files, "total_mb": round(total, 1)}


def describe_plan(plan: dict[str, Any]) -> str:
    lines = [f"DISK TEMIZLIGI - ~{plan['total_mb'] / 1024:.2f} GB"]
    for c in plan["cache"]:
        lines.append(f"• SIL: {CATEGORY_LABELS[c]}")
    for f in plan["files"][:12]:
        cloud = " (bulutta)" if f["cloud_only"] else ""
        lines.append(f"• COP KUTUSUNA: {Path(f['path']).name} {f['size_mb']:.0f} MB{cloud}")
    if len(plan["files"]) > 12:
        lines.append(f"• ... ve {len(plan['files']) - 12} dosya daha")
    return "\n".join(lines)


def _delete_tree_contents(root: Path, min_age_s: float) -> tuple[int, int]:
    """Kokun ICINI temizler (kok kalir). (silinen_bayt, atlanan_dosya)."""
    freed = skipped = 0
    now = time.time()
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            p = Path(dirpath, name)
            try:
                st = p.lstat()
                if min_age_s and now - st.st_mtime < min_age_s:
                    continue
                p.unlink()
                freed += st.st_size
            except OSError:
                skipped += 1  # kullanimda / izin yok
        if Path(dirpath) != root:
            try:
                Path(dirpath).rmdir()  # yalnizca bossa
            except OSError:
                pass
    return freed, skipped


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def send_to_recycle_bin(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    FO_DELETE = 0x0003
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    op = _SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(path) + "\0"  # cift NUL sonlandirma (ctypes ikincisini ekler)
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted and not path.exists()


def cleanup_run(categories: str = "", ids: str = "") -> dict[str, Any]:
    """Planlanan temizligi YAPAR. Onay ToolRunner'da alinir; dogrudan cagirma."""
    plan = plan_cleanup(categories, ids)
    if "error" in plan:
        return plan
    before = shutil.disk_usage(Path(os.environ.get("SystemDrive", "C:") + "\\")).free
    rows: list[list[Any]] = []
    stamp = datetime.now().isoformat(timespec="seconds")
    skipped_total = 0

    for cat in plan["cache"]:
        for root in cache_roots().get(cat, []):
            if is_protected(root) and cat != "windows_temp":
                continue
            age = TEMP_MIN_AGE_S if cat in ("temp", "windows_temp") else 0
            freed, skipped = _delete_tree_contents(root, age)
            skipped_total += skipped
            rows.append([stamp, cat, str(root), round(freed / MB, 1), "silindi", skipped])

    for f in plan["files"]:
        p = Path(f["path"])
        if not p.is_file() or is_protected(p):
            rows.append([stamp, "installers", str(p), f["size_mb"], "atlandi", 1])
            skipped_total += 1
            continue
        ok = send_to_recycle_bin(p)
        rows.append([stamp, "installers", str(p), f["size_mb"], "cop_kutusu" if ok else "hata", 0])
        skipped_total += 0 if ok else 1

    manifest = _scan_dir() / f"{datetime.now():%Y-%m-%d_%H%M}.csv"
    with manifest.open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["zaman", "kategori", "yol", "boyut_mb", "islem", "atlanan"])
        w.writerows(rows)
    after = shutil.disk_usage(Path(os.environ.get("SystemDrive", "C:") + "\\")).free
    logger.info(f"Disk temizligi: {len(rows)} islem, manifest {manifest}")
    return {
        "status": "tamam",
        "freed_mb": round(max(0, after - before) / MB, 1),
        "skipped_files": skipped_total,
        "recycled": [r[2] for r in rows if r[4] == "cop_kutusu"],
        "manifest": str(manifest),
        "disk": _drive_usage(),
        "note": ("Cop kutusuna tasinan dosyalar oradan geri yuklenebilir. Kilitli/kullanimdaki "
                 "dosyalar atlandi. Cop kutusu bosaltilmadikca o dosyalarin yeri bosalmaz."),
    }


def empty_recycle_bin() -> dict[str, Any]:
    """Geri Donusum Kutusu'nu bosaltir (GERI ALINAMAZ). Onay ToolRunner'da alinir."""
    if sys.platform != "win32":
        return {"error": "Yalnizca Windows"}
    before = recycle_bin_info()
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(
        None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
    if hr not in (0, -2147418113):  # E_UNEXPECTED: kutu zaten bos
        return {"error": f"Bosaltilamadi (hr={hr & 0xFFFFFFFF:#x})"}
    return {"status": "bosaltildi", "freed_mb": before.get("size_mb", 0), "disk": _drive_usage()}
