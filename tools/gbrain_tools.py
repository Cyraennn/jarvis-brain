"""GBrain araclari - kalici bilgi tabani (yaz / anlamsal ara / sor / belge ozeti)."""

from __future__ import annotations

from typing import Any

from agents.gbrain.store import get_gbrain, read_document_text


async def kb_write(title: str, content: str, tags: str = "") -> dict[str, Any]:
    """GBrain'e kalici bir not/bilgi yazar. tags virgulle ayrilir."""
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    return await get_gbrain().write(title, content, tag_list)


async def kb_search(query: str, k: int = 5) -> dict[str, Any]:
    """GBrain'de anlamsal arama yapar; en ilgili kayitlari dondurur."""
    hits = await get_gbrain().search(query, k=int(k))
    return {"query": query, "count": len(hits), "results": hits}


async def kb_ask(question: str) -> dict[str, Any]:
    """GBrain kayitlarindan bir soruyu yanitlar (retrieve + ozet)."""
    return await get_gbrain().ask(question)


def kb_recent(n: int = 10) -> dict[str, Any]:
    """Son eklenen GBrain kayitlarini listeler."""
    return {"notes": get_gbrain().recent(int(n)), **get_gbrain().stats()}


async def summarize_document(path: str, save_to_gbrain: bool = False) -> dict[str, Any]:
    """Bir belgeyi (txt/md/kod/pdf) ozetler; istege bagli GBrain'e kaydeder."""
    text, err = read_document_text(path)
    if err:
        return {"error": err}
    if not text.strip():
        return {"error": "belge bos gorunuyor"}

    from functools import lru_cache

    from agents.genai_util import generate_with_retry
    from config.settings import get_settings

    @lru_cache(maxsize=1)
    def _client():  # noqa: ANN202
        from google import genai
        from google.genai import types

        s = get_settings()
        return genai.Client(
            api_key=s.gemini_api_key,
            http_options=types.HttpOptions(api_version=s.agents_api_version, timeout=45_000),
        ), types

    client, types = _client()
    s = get_settings()
    resp = await generate_with_retry(
        client, model=s.agent_model_chain,
        contents=f"Asagidaki belgeyi Turkce, maddeli ve ozlu ozetle. Ana noktalar + "
                 f"varsa aksiyon maddeleri:\n\n{text}",
        config=types.GenerateContentConfig(temperature=0.2),
    )
    summary = (getattr(resp, "text", None) or "").strip()
    out: dict[str, Any] = {"path": path, "summary": summary, "chars": len(text)}
    if save_to_gbrain and summary:
        import os

        w = await get_gbrain().write(
            title=f"Belge ozeti: {os.path.basename(path)}",
            content=summary, tags=["belge", "ozet"],
        )
        out["gbrain"] = w
    return out
