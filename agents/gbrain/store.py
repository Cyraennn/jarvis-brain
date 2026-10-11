"""GBrain deposu - JSONL notlar + Gemini embeddings + kosinus arama.

Embed basarisizsa anahtar-kelime skorlamasina duser. `kb_ask` retrieve + Gemini yaniti.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import APP_DIR, get_settings

_DIR = APP_DIR / "data" / "gbrain"
_NOTES = _DIR / "notes.jsonl"


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 2}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class GBrain:
    def __init__(self) -> None:
        _DIR.mkdir(parents=True, exist_ok=True)
        self._notes: list[dict[str, Any]] = self._load()
        self._embed_warned = False

    # ------------------------------------------------------------------ io
    def _load(self) -> list[dict[str, Any]]:
        if not _NOTES.is_file():
            return []
        out = []
        for line in _NOTES.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _rewrite(self) -> None:
        """Tum kayitlari atomik olarak yeniden yazar (gecici dosya + replace)."""
        tmp = _NOTES.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(json.dumps(n, ensure_ascii=False) + "\n" for n in self._notes),
            encoding="utf-8",
        )
        tmp.replace(_NOTES)

    def _append(self, rec: dict[str, Any]) -> None:
        with _NOTES.open("a", encoding="utf-8") as h:
            h.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ embed
    @staticmethod
    @lru_cache(maxsize=1)
    def _client():  # noqa: ANN205
        from google import genai
        from google.genai import types

        s = get_settings()
        return genai.Client(
            api_key=s.gemini_api_key,
            http_options=types.HttpOptions(api_version=s.agents_api_version, timeout=30_000),
        )

    async def _embed(self, text: str) -> list[float]:
        try:
            client = self._client()
            s = get_settings()
            resp = await client.aio.models.embed_content(
                model=s.gbrain_embed_model, contents=text[:8000]
            )
            emb = resp.embeddings[0]
            return list(getattr(emb, "values", emb) or [])
        except Exception as exc:  # noqa: BLE001
            # Sessiz dusus anlamsal aramayi farkettirmeden bozuyordu: oturumda bir kez UYAR.
            log = logger.debug if self._embed_warned else logger.warning
            self._embed_warned = True
            log(f"GBrain embed hatasi (kelime moduna dusuluyor): {exc}")
            return []

    async def _reembed_stale(self, dim: int) -> int:
        """Gommesi bos veya boyutu `dim`den farkli kayitlari (eski/basarisiz model) yeniden gomer."""
        fixed = 0
        for n in self._notes:
            if len(n.get("embedding") or []) == dim:
                continue
            emb = await self._embed(f"{n.get('title', '')}\n{n.get('content', '')}")
            if len(emb) != dim:
                break  # embed calismiyor; bu turda vazgec
            n["embedding"] = emb
            fixed += 1
        if fixed:
            self._rewrite()
            logger.info(f"GBrain: {fixed} kaydin gommesi yenilendi.")
        return fixed

    # ------------------------------------------------------------------ API
    async def write(self, title: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
        content = (content or "").strip()
        if not content:
            return {"error": "icerik bos"}
        rec = {
            "id": uuid.uuid4().hex[:10],
            "ts": time.time(),
            "title": (title or content[:60]).strip(),
            "content": content,
            "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
            "embedding": await self._embed(f"{title}\n{content}"),
        }
        self._append(rec)
        self._notes.append(rec)

        out = {"status": "kaydedildi", "id": rec["id"], "title": rec["title"]}
        try:
            from tools.obsidian_sync import write_doc

            path = write_doc(rec["title"], content, "GBrain", rec["tags"])
            if path is not None:
                out["obsidian"] = str(path)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"GBrain Obsidian aynasi hatasi: {exc}")
        return out

    async def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not self._notes:
            return []
        q_emb = await self._embed(query)
        if q_emb:
            await self._reembed_stale(len(q_emb))
        scored: list[tuple[float, dict]] = []
        q_tokens = _tokenize(query)
        for n in self._notes:
            if q_emb and n.get("embedding"):
                score = _cosine(q_emb, n["embedding"])
            else:
                nt = _tokenize(n.get("title", "") + " " + n.get("content", ""))
                score = len(q_tokens & nt) / (len(q_tokens) or 1)
            scored.append((score, n))
        scored.sort(key=lambda x: -x[0])
        return [
            {"id": n["id"], "title": n["title"], "content": n["content"][:800],
             "tags": n.get("tags", []), "score": round(s, 3)}
            for s, n in scored[:max(1, k)] if s > 0.05
        ]

    async def ask(self, question: str, k: int = 5) -> dict[str, Any]:
        hits = await self.search(question, k=k)
        if not hits:
            return {"answer": "GBrain'de bu konuda kayit yok.", "sources": []}
        from agents.genai_util import generate_with_retry
        from google.genai import types

        context = "\n\n---\n".join(f"[{h['title']}]\n{h['content']}" for h in hits)
        s = get_settings()
        resp = await generate_with_retry(
            self._client(),
            model=s.agent_model_chain,
            contents=(
                f"Asagidaki GBrain kayitlarina dayanarak soruyu Turkce, kisa ve net "
                f"yanitla. Kayitlarda yoksa 'kayitlarda bu bilgi yok' de.\n\n"
                f"=== KAYITLAR ===\n{context}\n\n=== SORU ===\n{question}"
            ),
            config=types.GenerateContentConfig(temperature=0.2),
        )
        return {
            "answer": (getattr(resp, "text", None) or "").strip(),
            "sources": [{"id": h["id"], "title": h["title"]} for h in hits],
        }

    def recent(self, n: int = 10) -> list[dict[str, Any]]:
        return [
            {"id": r["id"], "title": r["title"], "tags": r.get("tags", []),
             "when": time.strftime("%d.%m.%Y %H:%M", time.localtime(r.get("ts", 0)))}
            for r in sorted(self._notes, key=lambda r: -r.get("ts", 0))[:max(1, n)]
        ]

    def stats(self) -> dict[str, Any]:
        return {"notes": len(self._notes),
                "embedded": sum(1 for n in self._notes if n.get("embedding"))}


@lru_cache(maxsize=1)
def get_gbrain() -> GBrain:
    return GBrain()


# --------------------------------------------------------------- belge ozeti

def read_document_text(path: str, max_chars: int = 20000) -> tuple[str, str | None]:
    """Bir belgeden duz metin cikarir. (text, hata) doner."""
    p = Path(path).expanduser()
    if not p.is_file():
        return "", f"Dosya yok: {p}"
    ext = p.suffix.lower()
    if ext == ".pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(str(p))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            return text[:max_chars], None
        except ImportError:
            return "", "PDF icin: pip install pypdf"
        except Exception as exc:  # noqa: BLE001
            return "", f"PDF okunamadi: {exc}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:max_chars], None
    except Exception as exc:  # noqa: BLE001
        return "", f"Okunamadi: {exc}"
