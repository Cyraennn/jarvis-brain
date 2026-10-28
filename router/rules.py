"""Bariz durumlar icin kurallar (~0 ms). Siniflandiricidan once calisir."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from router.registry import ModelRegistry

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic")
# "claude ile yap", "gemini modeliyle", "nemotron kullanarak", "using claude", "with gemini"
_EXPLICIT_TR = r"\b{name}\b\s*(?:ile|ıle|modeliyle|modelini kullan|kullanarak|kullan)\b"
_EXPLICIT_EN = r"\b(?:with|using|via)\s+{name}\b"


@dataclass
class RuleHit:
    rule: str
    chain: list[str]
    reason: str
    task_type: str | None = None
    explicit: bool = False
    extra: dict = field(default_factory=dict)


def explicit_model(text: str, registry: ModelRegistry) -> str | None:
    """Kullanici bir modeli ACIK niyetle adiyla istediyse onun kimligi."""
    low = (text or "").lower()
    names: dict[str, str] = dict(registry.aliases)
    names.update({m: m for m, info in registry.models.items() if info.routable})
    for name in sorted(names, key=len, reverse=True):
        esc = re.escape(name.lower())
        if re.search(_EXPLICIT_TR.format(name=esc), low) or re.search(_EXPLICIT_EN.format(name=esc), low):
            return names[name]
    return None


def has_image(attachments: list[str] | None) -> bool:
    for item in attachments or []:
        low = str(item).lower()
        if low.startswith("image/") or low.endswith(_IMAGE_EXT):
            return True
    return False


def match(*, text: str, context: str, attachments: list[str] | None, forced_task_type: str | None,
          registry: ModelRegistry) -> RuleHit | None:
    if forced_task_type == "qa":
        name, chain = registry.chain_for("qa", "zor")
        return RuleHit("qa", chain, "QA karari: hiz icin kaliteden odun verilmez, en guclu model",
                       task_type="qa", extra={"chain_name": name})
    model = explicit_model(text, registry)
    if model:
        _, tail = registry.chain_for("sohbet", "zor")
        return RuleHit("explicit_model", [model, *[m for m in tail if m != model]],
                       f"kullanici modeli acikca istedi: {model}", explicit=True,
                       extra={"chain_name": "acik_istek"})
    if has_image(attachments):
        name, chain = registry.chain_for("gorsel", "orta")
        return RuleHit("image_attachment", chain, "gorsel eki var -> vision modeli",
                       task_type="gorsel", extra={"chain_name": name})
    if len(text or "") + len(context or "") > registry.long_context_chars:
        chain = list(registry.chains.get("uzun_baglam") or registry.chains[registry.default_chain])
        return RuleHit("long_context", chain,
                       f"cok uzun baglam (> {registry.long_context_chars} karakter) -> long_context",
                       extra={"chain_name": "uzun_baglam"})
    return None
