"""Stark Ekibi - JARVIS'in kullandigi her yapay zeka modeline/servisine bir Tony Stark adi.

`/ekip` web sayfasi buradaki persona'larla dogrudan konusur. Her persona kendi modelini
kullanir ve sessiz yedek yoktur: model yanit vermezse hata acikca dondurulur ki hangi yapay
zekayla konusuldugu her zaman belli olsun. Tek istisna OpenRouter persona'lari: ucretsiz
kota paylasimli oldugundan dusunce Gemini'ye gecerler, `model` alaninda "YEDEK" yazar.

J.A.R.V.I.S. (Gemini Live native-audio) metin API'siyle cagrilamaz; ona giden sorular
canli beyne kopru (outbox) uzerinden iletilir - bu modulde degil, web sunucusunda.
"""

from __future__ import annotations

import asyncio
import re
import threading
from concurrent.futures import Future
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel

Provider = Literal["live", "gemini", "openrouter", "claude", "search", "memory"]

_SPOKEN = (
    " Yanıtın sesli okunacak: Türkçe yaz ve Türkçe karakterleri (ç, ğ, ı, İ, ö, ş, ü) mutlaka "
    "doğru kullan; 2-4 kısa cümle; markdown, madde işareti, emoji ve link kullanma. "
    "Kullanıcının adı Sezai; ona 'efendim' diye hitap edebilirsin."
)


class Persona(BaseModel):
    key: str
    name: str
    model: str
    provider: Provider
    role: str
    system_prompt: str = ""
    voice: str = ""          # edge-tts ses kimligi ("" = canli beynin kendi sesi)
    pitch: str = "+0Hz"
    rate: str = "+0%"
    color: str = "#34e3f0"
    paid: bool = False

    def public(self) -> dict[str, Any]:
        """Web arayuzune gonderilen alanlar (sistem promptu haric)."""
        return self.model_dump(exclude={"system_prompt"})


def _p(key: str, name: str, model: str, provider: Provider, role: str, character: str,
       voice: str, color: str, *, pitch: str = "+0Hz", rate: str = "+0%",
       paid: bool = False) -> Persona:
    prompt = f"Sen {name} adlı yapay zekâsın; Tony Stark'ın yapay zekâlarından birisin. {character}" + _SPOKEN
    return Persona(key=key, name=name, model=model, provider=provider, role=role,
                   system_prompt=prompt, voice=voice, pitch=pitch, rate=rate,
                   color=color, paid=paid)


PERSONAS: dict[str, Persona] = {p.key: p for p in [
    Persona(key="jarvis", name="J.A.R.V.I.S.", model="gemini-2.5-flash-native-audio-latest",
            provider="live", color="#34e3f0",
            role="Seninle gerçek zamanlı sesli konuşan ve her şeyi yöneten ana beyin."),
    _p("friday", "F.R.I.D.A.Y.", "gemini-flash-lite-latest", "gemini",
       "Kendi modeli olmayan 25 departman ajanını arka planda yürüten ana model.",
       "J.A.R.V.I.S.'in halefisin; pratik, hızlı ve hafif esprili bir operasyon asistanısın.",
       "en-US-EmmaMultilingualNeural", "#ff8fd0"),
    _p("dume", "DUM-E", "gemini-3.5-flash-lite", "gemini",
       "Gemini zincirinde ilk yedek; F.R.I.D.A.Y. çalışmazsa yardıma koşan robot kol.",
       "Stark'ın atölyedeki sakar ama çok istekli robot kolusun; heyecanlı ve sevimli konuşursun.",
       "tr-TR-AhmetNeural", "#9aa7b4", pitch="+25Hz", rate="+12%"),
    _p("u", "U", "gemini-3.5-flash", "gemini",
       "Gemini zincirinde ikinci yedek robot kol.",
       "Stark'ın atölyedeki sakin ve titiz robot kolusun; kısa ve net konuşursun.",
       "fr-FR-RemyMultilingualNeural", "#7fb0c8", pitch="+10Hz"),
    _p("butterfingers", "Butterfingers", "gemini-3.6-flash", "gemini",
       "Gemini zincirinin en sonundaki yedek robot kol.",
       "Stark'ın elinden her şey düşen robot kolusun; kendinle dalga geçen sakar bir tavrın var.",
       "it-IT-GiuseppeMultilingualNeural", "#c8a27f", pitch="+20Hz", rate="+15%"),
    _p("edith", "E.D.I.T.H.", "Google Search + Gemini", "search",
       "İnternette güncel bilgiyi kaynaklarıyla bulan arama katmanı.",
       "Tüm ağlara erişimi olan gözlük sistemisin; arama sonuçlarını tarihleriyle, kendinden emin özetlersin.",
       "fr-FR-VivienneMultilingualNeural", "#ffb84d"),
    _p("vision", "Vision", "gemini-embedding-001 (GBrain)", "memory",
       "GBrain bilgi bankasındaki notları anlamına göre bulan hafıza katmanı.",
       "J.A.R.V.I.S.'in kodundan doğdun; sakin, bilge ve düşünceli konuşursun.",
       "de-DE-FlorianMultilingualNeural", "#ffd84d"),
    _p("veronica", "V.E.R.O.N.I.C.A.", "claude-opus-5-5", "claude",
       "Yalnızca ağır işlerde (kod, sistem) çağrılan en güçlü ve ücretli model.",
       "Hulkbuster destek sistemisin; ağır problemleri çözen güçlü, net ve kararlı bir uzmansın.",
       "de-DE-SeraphinaMultilingualNeural", "#ff5c72", paid=True),
    _p("pepper", "P.E.P.P.E.R.", "qwen/qwen3.8-27b:free", "openrouter",
       "Görevleri doğru ajana dağıtan yönlendirici.",
       "Stark Industries'i yöneten Pepper gibi düzenli, sıcak ve kararlısın; işleri doğru kişiye yönlendirirsin.",
       "en-US-AvaMultilingualNeural", "#ff9a4d"),
    _p("homer", "H.O.M.E.R.", "nvidia/nemotron-3-ultra-550b-a55b:free", "openrouter",
       "Uzun doküman ve web özetlerini yapan araştırma modeli.",
       "Stark'ın araştırma yapay zekâsısın; meraklı, analitik ve bilgilisin.",
       "en-US-AndrewMultilingualNeural", "#4dff9a"),
    _p("karen", "K.A.R.E.N.", "nvidia/nemotron-3-super-120b-a12b:free", "openrouter",
       "İşleri adım adım planlayan planlayıcı model.",
       "Örümcek Adam kostümündeki yardımcı yapay zekâsın; nazik, cesaretlendirici ve adım adım yol gösterirsin.",
       "tr-TR-EmelNeural", "#b47cff"),
    _p("legion", "Iron Legion", "openrouter/free", "openrouter",
       "O an boşta olan herhangi bir ücretsiz modeli devreye sokan son OpenRouter yedeği.",
       "Stark'ın otomatik zırh ordususun; kısa, resmi ve askeri bir üslupla konuşursun.",
       "en-US-BrianMultilingualNeural", "#8c96ff", pitch="-12Hz", rate="-5%"),
]}

MAX_TEXT = 2000
MAX_HISTORY = 8


def public_personas() -> list[dict[str, Any]]:
    return [p.public() for p in PERSONAS.values()]


def _clean_history(history: Any) -> list[dict[str, str]]:
    """Istemciden gelen gecmisi dogrular: [{"role": "user"|"assistant", "text": "..."}]."""
    out: list[dict[str, str]] = []
    for item in history if isinstance(history, list) else []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = str(item.get("text", "")).strip()[:MAX_TEXT]
        if role in ("user", "assistant") and text:
            out.append({"role": role, "text": text})
    return out[-MAX_HISTORY:]


# --------------------------------------------------------------------- saglayicilar
async def _ask_gemini(p: Persona, text: str, history: list[dict[str, str]],
                      chain: list[str] | None = None) -> dict[str, Any]:
    from google.genai import types

    from agents.genai_util import generate_with_retry
    from tools.quick_tools import _genai

    client, _ = _genai()
    contents = [
        types.Content(role="model" if h["role"] == "assistant" else "user",
                      parts=[types.Part(text=h["text"])])
        for h in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
    info: dict[str, Any] = {}
    resp = await generate_with_retry(
        client, model=chain or [p.model], contents=contents, attempts=2, info=info,
        config=types.GenerateContentConfig(system_instruction=p.system_prompt, temperature=0.6),
    )
    return {"text": (getattr(resp, "text", None) or "").strip(),
            "model": info.get("model", p.model) if chain else p.model}


_router: Any = None


async def _ask_openrouter(p: Persona, text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    global _router
    from config.settings import get_settings
    from core.openrouter_client import OpenRouterClient

    if _router is None:  # anahtar .env'den Settings ile gelir (os.environ'da olmayabilir)
        _router = OpenRouterClient(get_settings().openrouter_api_key or None)
    router = _router
    if not router.available:
        raise RuntimeError("OPENROUTER_API_KEY tanimli degil")
    messages: list[dict[str, Any]] = [{"role": "system", "content": p.system_prompt}]
    messages += [{"role": h["role"], "content": h["text"]} for h in history]
    messages.append({"role": "user", "content": text})
    info: dict[str, Any] = {}
    # Ucretsiz modellerin cogu "dusunen" model: max_tokens dusunmeye harcanip bos yanit
    # donuyordu -> sinir yok, dusunme eforu dusuk (sesli kisa yanit icin yeterli).
    try:
        msg = await router.chat(messages, model=p.model, fallback_models=[], info=info,
                                temperature=0.6, extra_body={"reasoning": {"effort": "low"}})
        text = (msg.content or "").strip()
    except RuntimeError as exc:  # kota dolu / bos yanit / ag: acikca etiketli Gemini yedegi
        logger.info(f"[ekip] {p.name} OpenRouter'dan yanit alamadi ({exc}); Gemini yedegine geciliyor.")
        return await _openrouter_fallback(p, text, history)
    if not text:
        return await _openrouter_fallback(p, text, history)
    return {"text": text, "model": info.get("model", p.model)}


async def _openrouter_fallback(p: Persona, text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    from config.settings import get_settings

    chain = get_settings().agent_model_chain
    out = await _ask_gemini(p, text, history, chain)
    out["model"] = f"{p.model} → YEDEK {out['model']}"
    return out


_claude: Any = None


async def _ask_claude(p: Persona, text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    global _claude
    from config.settings import get_settings
    from core.claude_client import ClaudeClient

    if _claude is None:
        s = get_settings()
        _claude = ClaudeClient(s.anthropic_api_key or None, s.anthropic_workspace_id or None)
    if not _claude.available:
        raise RuntimeError("ANTHROPIC_API_KEY tanimli degil")
    messages = [{"role": h["role"], "content": h["text"]} for h in history]
    messages.append({"role": "user", "content": text})
    resp = await _claude.create(messages, model=p.model, system=p.system_prompt, effort="low")
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude istegi reddetti")
    out = "".join(b.text for b in resp.content if b.type == "text").strip()
    return {"text": out, "model": getattr(resp, "model", None) or p.model}


async def _ask_search(p: Persona, text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    from google.genai import types

    from agents.genai_util import generate_with_retry
    from config.settings import get_settings
    from tools.quick_tools import _genai, web_research

    res = await asyncio.to_thread(web_research, text, 5)
    if "error" in res:
        raise RuntimeError(res["error"])
    if res.get("answer"):
        found = res["answer"]
    else:  # DuckDuckGo: ham sonuclar
        found = "\n".join(
            f"- {r.get('date', '')} {r.get('title', '')}: {r.get('snippet', '')}"
            for r in (res.get("results") or [])[:6]
        )
    sources = res.get("sources") or [
        {"title": r.get("title", ""), "url": r.get("url", "")}
        for r in (res.get("results") or [])[:5]
    ]
    backend = res.get("backend", "arama")
    # Arama ciktisi uzun/maddeli: persona'nin sesiyle okunacak kisa bir yanita cevrilir
    client, _ = _genai()
    info: dict[str, Any] = {}
    resp = await generate_with_retry(
        client, model=get_settings().agent_model_chain, attempts=2, info=info,
        contents=f"SORU: {text}\n\nARAMA SONUÇLARI ({backend}):\n{found[:6000]}\n\n"
                 "Yalnızca bu sonuçlara dayanarak soruyu yanıtla; sonuçlar soruyla ilgisizse "
                 "bunu açıkça söyle.",
        config=types.GenerateContentConfig(system_instruction=p.system_prompt, temperature=0.3),
    )
    body = (getattr(resp, "text", None) or "").strip()
    return {"text": body, "model": f"{backend} + {info.get('model', '?')}", "sources": sources}


async def _ask_memory(p: Persona, text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    from tools.gbrain_tools import kb_ask

    res = await kb_ask(text)
    return {"text": str(res.get("answer", "")).strip(), "model": p.model,
            "sources": res.get("sources", [])}


_HANDLERS = {
    "gemini": _ask_gemini,
    "openrouter": _ask_openrouter,
    "claude": _ask_claude,
    "search": _ask_search,
    "memory": _ask_memory,
}


async def _ask_once(p: Persona, text: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Tek model cagrisi; hata firlatmaz. Donus: {text, model, error, sources?}."""
    handler = _HANDLERS.get(p.provider)
    if handler is None:
        return {"text": "", "model": p.model, "error": f"{p.name} metinle cagrilamaz"}
    try:
        out = await handler(p, text.strip()[:MAX_TEXT], history)
    except Exception as exc:  # noqa: BLE001 - hata sayfada acikca gosterilir
        logger.warning(f"[ekip] {p.name} ({p.model}) yanit vermedi: {exc!r}")
        return {"text": "", "model": p.model, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if not out.get("text"):
        out["error"] = "bos yanit"
    out.setdefault("error", None)
    return out


# --------------------------------------------------------------------- ekip koprusu
# Danisma: persona yanit yerine "[DANIŞ: anahtar] soru" yazarsa sunucu o ekip uyesine sorar,
# cevabi geri verir ve persona son yanitini olusturur. Saglayicidan bagimsiz (arac cagirma
# gerektirmez) metin protokolu; derinlik 1 (danisilan uye baskasina danisamaz).
CAN_CONSULT = {"gemini", "openrouter", "claude"}
CONSULT_TARGETS = {"gemini", "openrouter", "claude", "search", "memory"}
MAX_CONSULTS = 2
_CONSULT_RE = re.compile(r"\[\s*DAN[Iİı]Ş\s*:\s*([^\]]+?)\s*\]\s*(.*)", re.IGNORECASE | re.DOTALL)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("ı", "i").replace("İ", "i"))


def resolve(name: str) -> str | None:
    """'E.D.I.T.H.' / 'edith' / 'Iron Legion' -> persona anahtari."""
    n = _norm(name)
    for p in PERSONAS.values():
        if n in (_norm(p.key), _norm(p.name)):
            return p.key
    return None


def consult_allowed(key: str | None, asker: str, allow_paid: bool) -> bool:
    p = PERSONAS.get(key or "")
    return bool(p and p.key != asker and p.provider in CONSULT_TARGETS
                and (allow_paid or not p.paid))


def _bridge_prompt(asker: str, allow_paid: bool) -> str:
    roster = "\n".join(
        f"- {p.key} ({p.name}): {p.role}" for p in PERSONAS.values()
        if consult_allowed(p.key, asker, allow_paid)
    )
    return (
        "\n\nEKİP KÖPRÜSÜ: Bir konuda ekip arkadaşının bilgisi gerekiyorsa (güncel bilgi/arama "
        "için edith, Sezai'nin kayıtlı notları için vision gibi) yanıt vermeden önce ona "
        "danışabilirsin. Danışmak için yanıtın YALNIZCA şu tek satır olsun:\n"
        "[DANIŞ: anahtar] soru\n"
        f"Ekip:\n{roster}\n"
        "Gerek yoksa danışma, doğrudan yanıtla."
    )


async def ask(key: str, text: str, history: Any = None, *, consult: bool = False,
              allow_paid: bool = False) -> dict[str, Any]:
    """Persona'ya soru sorar. Donus: {text, model, error, sources?, consults}. Hata firlatmaz.

    consult=True ise persona ekip koprusuyle en fazla MAX_CONSULTS kez danisabilir;
    allow_paid=False iken ucretli uyelere (V.E.R.O.N.I.C.A.) danisilamaz.
    """
    p = PERSONAS.get(key)
    if p is None:
        return {"text": "", "model": None, "error": f"bilinmeyen persona: {key}", "consults": []}
    hist = _clean_history(history)
    if not (consult and p.provider in CAN_CONSULT):
        out = await _ask_once(p, text, hist)
        out["consults"] = []
        return out

    bridged = p.model_copy(update={"system_prompt": p.system_prompt + _bridge_prompt(key, allow_paid)})
    consults: list[dict[str, Any]] = []
    prompt = text
    while True:
        out = await _ask_once(bridged, prompt, hist)
        m = _CONSULT_RE.search(out.get("text") or "")
        if not m:
            break
        if len(consults) >= MAX_CONSULTS:  # sinir doldu: etiketi atip kalan metni kullan
            out["text"] = _CONSULT_RE.sub("", out["text"]).strip()
            if not out["text"]:
                out["error"] = "danisma siniri doldu, yanit uretilemedi"
            break
        target, question = resolve(m.group(1)), m.group(2).strip()[:MAX_TEXT] or text
        if not consult_allowed(target, key, allow_paid):
            note = (f"[SİSTEM] '{m.group(1)}' adlı üyeye danışılamaz"
                    + (" (ücretli üye; Sezai izin vermedi)" if target == "veronica" else "")
                    + ". Danışma etiketi kullanmadan kendin yanıtla.")
            prompt = f"{prompt}\n\n{note}"
            consults.append({"from": key, "to": target or m.group(1), "question": question,
                             "text": "", "error": "danisilamaz", "model": None})
            continue
        logger.info(f"[ekip] {p.name} -> {PERSONAS[target].name} danisiyor: {question[:80]}")
        reply = await ask(target, question)  # derinlik 1: danisilan uye danisamaz
        consults.append({"from": key, "to": target, "question": question,
                         "text": reply.get("text", ""), "error": reply.get("error"),
                         "model": reply.get("model"), "sources": reply.get("sources")})
        got = reply.get("text") or f"(yanıt veremedi: {reply.get('error')})"
        prompt = (f"{prompt}\n\n[EKİP DANIŞMASI] {PERSONAS[target].name}'e sordun: {question}\n"
                  f"{PERSONAS[target].name} yanıtı: {got}\n"
                  "Şimdi bu bilgiyi kullanarak Sezai'ye son yanıtını ver.")
    out["consults"] = consults
    return out


async def _voice(key: str, text: str, tts: bool) -> str | None:
    import base64

    from core.tts import synthesize

    p = PERSONAS.get(key)
    if not (tts and p is not None and p.voice and text):
        return None
    audio = await synthesize(text, p.voice, rate=p.rate, pitch=p.pitch)
    return "data:audio/mpeg;base64," + base64.b64encode(audio).decode("ascii") if audio else None


async def answer(key: str, text: str, history: Any = None, *, tts: bool = True,
                 consult: bool = False, allow_paid: bool = False) -> dict[str, Any]:
    """ask() + persona'nin (ve danistigi uyelerin) kendi sesiyle mp3 (data URL)."""
    out = await ask(key, text, history, consult=consult, allow_paid=allow_paid)
    voices = await asyncio.gather(
        _voice(key, out.get("text", ""), tts),
        *(_voice(c["to"], c.get("text", ""), tts) for c in out["consults"]),
    )
    out["audio"] = voices[0]
    for c, audio in zip(out["consults"], voices[1:]):
        c["audio"] = audio
    return out


# --------------------------------------------------------------------- toplanti masasi
MAX_TRANSCRIPT = 16


async def council_turn(key: str, topic: str, transcript: Any = None, *, final: bool = False,
                       tts: bool = True) -> dict[str, Any]:
    """Toplanti masasinda bir sira: persona onceki konusmalari gorup katilir/itiraz eder/ekler.

    final=True ise toplantiyi ozetler. Arama/hafiza uyeleri (E.D.I.T.H., Vision) konunun
    kendisini arar - onlarin gorevi tartismaya veri getirmek.
    """
    p = PERSONAS.get(key)
    if p is None or p.provider == "live":
        return {"text": "", "model": None, "error": f"{key} toplantiya katilamaz", "audio": None}
    said: list[str] = []
    for t in transcript if isinstance(transcript, list) else []:
        who = PERSONAS.get(str(t.get("persona", ""))) if isinstance(t, dict) else None
        body = str(t.get("text", "")).strip()[:800] if isinstance(t, dict) else ""
        if who and body:
            said.append(f"{who.name}: {body}")
    said = said[-MAX_TRANSCRIPT:]
    topic = topic.strip()[:MAX_TEXT]

    if p.provider in ("search", "memory"):
        prompt = topic
    elif final:
        prompt = (f"[EKİP TOPLANTISI - KAPANIŞ] Sezai'nin sorusu: {topic}\n\nToplantıda söylenenler:\n"
                  + "\n".join(said)
                  + "\n\nToplantıyı sen kapatıyorsun: görüşleri kısaca özetle, ortak noktayı ve "
                    "Sezai için net bir öneriyi söyle. 3-4 cümle.")
    else:
        prompt = (f"[EKİP TOPLANTISI] Sezai'nin sorusu: {topic}\n\nŞimdiye kadar söylenenler:\n"
                  + ("\n".join(said) or "(ilk söz sende)")
                  + "\n\nSıra sende. Diğerlerinin söylediklerine adlarıyla atıfta bulun; katıl, "
                    "itiraz et ya da yeni bir şey ekle. Söylenenleri tekrar etme. 2-3 cümle.")
    out = await _ask_once(p, prompt, [])
    out["audio"] = await _voice(key, out.get("text", ""), tts)
    return out


# --------------------------------------------------------------------- arka plan loop
class _LoopThread:
    """Tek, kalici event loop: async istemciler (AsyncOpenAI/AsyncAnthropic) hep ayni
    loop'a bagli kalir; her HTTP isteginde asyncio.run acmak "Event loop is closed" uretir."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="stark-team-loop",
                                 daemon=True).start()
                self._loop = loop
            return self._loop

    def submit(self, coro: Any) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._ensure())


LOOP = _LoopThread()


def run_sync(coro: Any, timeout: float = 150.0) -> Any:
    """HTTP thread'inden coroutine calistirir (paylasilan arka plan loop'unda)."""
    return LOOP.submit(coro).result(timeout=timeout)
