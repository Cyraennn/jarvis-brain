"""Markdown Denetci yetenegi (TECH departmani).

Bir dosyayi veya dizini tarar; baslik hiyerarsisi, kirik baglar/gorseller, bicim
tutarsizliklari ve isaretcileri raporlar. Tamamen deterministik - LLM gerektirmez.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_LINK = re.compile(r"(?<!\!)\[([^\]]*)\]\(([^)]+)\)")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_BARE_URL = re.compile(r"(?<![(<\]\w])(https?://[^\s)>\]]+)")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+\S")
_TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "data"}


def _iter_markdown(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in {".md", ".markdown"} else []
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in {".md", ".markdown"}):
            continue
        # atlama listesi yalnizca tarama kokunun ALTINDAKI klasorlere uygulanir
        rel_parts = p.relative_to(root).parts[:-1]
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        out.append(p)
    return out


def _audit_file(path: Path, root: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [{"line": 0, "severity": "error", "rule": "read", "message": str(exc)}]

    issues: list[dict[str, Any]] = []
    in_fence = False
    fence_marker = ""
    h1_count = 0
    last_level = 0
    list_markers: set[str] = set()

    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        # kod blogu sinirlari
        fence = re.match(r"^(```+|~~~+)", stripped)
        if fence:
            token = fence.group(1)[0] * 3
            if not in_fence:
                in_fence, fence_marker = True, token
            elif stripped.startswith(fence_marker):
                in_fence = False
            continue
        if in_fence:
            continue

        if raw != raw.rstrip():
            issues.append({"line": i, "severity": "info", "rule": "trailing-space",
                           "message": "Satir sonunda bosluk"})
        if "\t" in raw:
            issues.append({"line": i, "severity": "info", "rule": "tab",
                           "message": "Sekme karakteri (bosluk kullanin)"})

        m = _HEADING.match(stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if not text:
                issues.append({"line": i, "severity": "error", "rule": "empty-heading",
                               "message": "Bos baslik"})
            if level == 1:
                h1_count += 1
            if last_level and level > last_level + 1:
                issues.append({"line": i, "severity": "warning", "rule": "heading-jump",
                               "message": f"Baslik seviyesi atlandi (H{last_level} -> H{level})"})
            last_level = level

        lm = _LIST_ITEM.match(raw)
        if lm and not lm.group(1):
            marker = lm.group(2)
            list_markers.add("ordered" if marker[0].isdigit() else marker)

        for alt, target in _MD_IMAGE.findall(raw):
            if not alt.strip():
                issues.append({"line": i, "severity": "warning", "rule": "img-alt",
                               "message": f"Gorselde alt metni yok: {target}"})
            _check_link_target(target, path, root, i, issues, kind="gorsel")

        for _label, target in _MD_LINK.findall(raw):
            _check_link_target(target, path, root, i, issues, kind="bag")

        for url in _BARE_URL.findall(raw):
            issues.append({"line": i, "severity": "info", "rule": "bare-url",
                           "message": f"Ciplak URL (baglantiya sarin): {url[:60]}"})

        if _TODO.search(raw):
            issues.append({"line": i, "severity": "info", "rule": "todo",
                           "message": f"Isaretci: {stripped[:70]}"})

    if h1_count == 0:
        issues.append({"line": 1, "severity": "warning", "rule": "no-h1",
                       "message": "Dosyada H1 baslik yok"})
    elif h1_count > 1:
        issues.append({"line": 1, "severity": "warning", "rule": "multi-h1",
                       "message": f"{h1_count} adet H1 (tek olmali)"})
    real_markers = {m for m in list_markers if m != "ordered"}
    if len(real_markers) > 1:
        issues.append({"line": 1, "severity": "info", "rule": "list-marker",
                       "message": f"Karisik liste isaretleri: {sorted(real_markers)}"})

    issues.sort(key=lambda x: (_SEVERITY_ORDER.get(x["severity"], 3), x["line"]))
    return issues


def _check_link_target(
    target: str, path: Path, root: Path, line: int, issues: list, kind: str
) -> None:
    target = target.split()[0].strip("<>")
    if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
        return
    if target.startswith("data:"):
        return
    ref = (path.parent / target.split("#", 1)[0]).resolve()
    if not ref.exists():
        try:
            rel = ref.relative_to(root)
        except ValueError:
            rel = ref
        issues.append({"line": line, "severity": "error", "rule": "broken-link",
                       "message": f"Kirik {kind}: {target}  (-> {rel})"})


def audit_markdown(target: str = "", root: str = "") -> dict[str, Any]:
    """Markdown dosya/dizinini denetler ve yapisal bir rapor dondurur.

    target : denetlenecek dosya veya dizin (bos ise proje koku)
    """
    base = Path(root).expanduser() if root else BASE_DIR
    scan = Path(target).expanduser() if target else base
    if not scan.is_absolute():
        scan = (base / scan)
    if not scan.exists():
        return {"error": f"Yol bulunamadi: {scan}"}

    files = _iter_markdown(scan)
    per_file: list[dict[str, Any]] = []
    totals = {"error": 0, "warning": 0, "info": 0}

    for f in files:
        issues = _audit_file(f, base)
        for it in issues:
            totals[it["severity"]] = totals.get(it["severity"], 0) + 1
        if issues:
            try:
                rel = str(f.relative_to(base))
            except ValueError:
                rel = str(f)
            per_file.append({"file": rel, "issue_count": len(issues), "issues": issues[:40]})

    per_file.sort(key=lambda x: -x["issue_count"])
    clean = len(files) - len(per_file)
    return {
        "skill": "markdown_auditor",
        "scanned_path": str(scan),
        "files_scanned": len(files),
        "files_clean": clean,
        "files_with_issues": len(per_file),
        "totals": totals,
        "files": per_file[:25],
        "summary": (
            f"{len(files)} markdown dosyasi tarandi. "
            f"{totals['error']} hata, {totals['warning']} uyari, {totals['info']} bilgi. "
            f"{clean} dosya temiz."
        ),
    }
