"""Tarayici ajani: Playwright ile kontrollu Chromium'da gezinme, tiklama, form doldurma.

- Kalici ayri profil (`data/browser_profile`) - WhatsApp profiliyle cakismaz; kullanici
  bir kez elle giris yapar, oturum hatirlanir.
- `browser_snapshot` sayfadaki gorunur etkilesimli ogelere numara (ref) verir; ajan
  `[N] buton "Giris yap"` listesine bakip `browser_click(N)` / `browser_type(N, ...)` der.
  Vision gerekmez, token acisindan ucuzdur.
- Guvenlik: odeme/satin alma/silme butonlari, kart alanlari ve sifre alanlari ajan
  tarafindan kullanilamaz (yalnizca kullanici elle yapar).

Tum Playwright nesneleri `core.async_worker` loop'unda yasar.
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from config.settings import APP_DIR, get_settings
from core.async_worker import get_worker

NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000
SUBMIT_TIMEOUT_S = 60.0
MAX_ELEMENTS = 80
DEFAULT_TEXT_CHARS = 3000

_DANGER_TEXT = re.compile(
    r"(satin al|satın al|siparis|sipariş|\bode\b|\böde\b|odeme|ödeme|sepeti onayla|"
    r"hesabi sil|hesabı sil|\bsil\b|kalici|kalıcı|"
    r"\bbuy\b|purchase|checkout|place order|\bpay\b|payment|confirm order|delete|remove account)",
    re.IGNORECASE,
)

# Gorunur etkilesimli ogelere data-cyraen-ref atar ve ozet dondurur.
_SNAPSHOT_JS = r"""
(maxItems) => {
  document.querySelectorAll('[data-cyraen-ref]').forEach(e => e.removeAttribute('data-cyraen-ref'));
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, ' +
              '[role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], ' +
              '[role=option], [contenteditable=true], [onclick]';
  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (el.disabled) continue;
    n += 1;
    el.setAttribute('data-cyraen-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const field = tag === 'input' || tag === 'select' || tag === 'textarea';
    const forLabel = field && el.labels && el.labels.length ? el.labels[0].innerText : '';
    const label = (el.getAttribute('aria-label') ||
                   (field ? (forLabel || el.getAttribute('placeholder') || el.getAttribute('title') ||
                             el.getAttribute('name') || el.id ||
                             (tag === 'select' && el.selectedOptions[0] ? el.selectedOptions[0].text : '') ||
                             (el.type === 'submit' || el.type === 'button' ? el.value : ''))
                          : (el.innerText || el.getAttribute('title') || el.getAttribute('alt') || el.value)) ||
                   '').trim().replace(/\s+/g, ' ');
    let kind = el.getAttribute('role') || tag;
    if (tag === 'input') kind = 'input:' + (el.getAttribute('type') || 'text');
    if (tag === 'a') kind = 'link';
    const item = {ref: n, kind, label: label.slice(0, 80)};
    if (tag === 'a') item.href = (el.getAttribute('href') || '').slice(0, 120);
    if (tag === 'select') item.options = Array.from(el.options).slice(0, 15).map(o => o.text.trim());
    if ((tag === 'input' || tag === 'textarea') && el.value && el.type !== 'password') item.value = String(el.value).slice(0, 60);
    if (r.top > window.innerHeight || r.bottom < 0) item.offscreen = true;
    out.push(item);
    if (out.length >= maxItems) break;
  }
  return {total: n, items: out};
}
"""

_GUARD_JS = r"""
(el) => {
  const form = el.closest('form');
  const fieldsIn = (root) => root ? Array.from(root.querySelectorAll('input')) : [];
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  const inForm = fieldsIn(form);
  return {
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').toLowerCase(),
    text: ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim().slice(0, 120),
    card: ac.startsWith('cc-') || inForm.some(i => (i.getAttribute('autocomplete') || '').toLowerCase().startsWith('cc-')),
    password: el.type === 'password',
    submitsPassword: !!form && (el.type === 'submit' || el.tagName === 'BUTTON') &&
                     inForm.some(i => i.type === 'password' && i.value),
  };
}
"""


class BrowserSession:
    def __init__(self) -> None:
        self._pw: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self._registered = False

    # ------------------------------------------------------------ lifecycle
    async def _ensure_page(self) -> Any:
        if self._page is not None and not self._page.is_closed():
            return self._page
        if self._ctx is None:
            from playwright.async_api import async_playwright

            s = get_settings()
            profile = Path(s.browser_profile_dir)
            profile.mkdir(parents=True, exist_ok=True)
            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=s.browser_headless,
                locale="tr-TR",
                viewport={"width": 1280, "height": 860},
            )
            self._ctx.set_default_timeout(ACTION_TIMEOUT_MS)
            self._ctx.on("close", lambda *_: self._reset())
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        self._page = pages[-1] if pages else await self._ctx.new_page()
        return self._page

    def _reset(self) -> None:
        self._ctx = None
        self._page = None

    async def aclose(self) -> None:
        try:
            if self._ctx is not None:
                await self._ctx.close()
        finally:
            self._reset()
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _blocked(url: str) -> str | None:
        host = (urlparse(url).hostname or "").lower()
        for dom in get_settings().browser_blocked_domains:
            if host == dom or host.endswith("." + dom):
                return dom
        return None

    async def _element(self, ref: int) -> Any:
        page = await self._ensure_page()
        loc = page.locator(f'[data-cyraen-ref="{int(ref)}"]')
        if await loc.count() == 0:
            raise LookupError(f"ref {ref} bulunamadi; once browser_snapshot cagir (sayfa degismis olabilir).")
        return loc.first

    async def _guard(self, loc: Any, action: str) -> str | None:
        info = await loc.evaluate(_GUARD_JS)
        if info["card"]:
            return "Kart/odeme alanlarina ajan dokunamaz; kullanici elle yapmali."
        if info["password"] and action == "type":
            return "Sifre alanina ajan yazamaz; kullanici bir kez elle giris yapmali (profil hatirlar)."
        if action == "click" and info["submitsPassword"]:
            return "Sifreli form gonderimi kullanici tarafindan yapilmali."
        if action == "click" and _DANGER_TEXT.search(info["text"] or ""):
            return f"'{info['text'][:60]}' geri alinamaz bir islem gibi gorunuyor; kullanici onayi/elle yapmasi gerekir."
        return None

    async def _state(self, page: Any) -> dict[str, Any]:
        return {"url": page.url, "title": await page.title()}

    # ------------------------------------------------------------ actions
    async def open(self, url: str) -> dict[str, Any]:
        url = (url or "").strip()
        if not url:
            return {"error": "'url' zorunlu."}
        if not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.IGNORECASE):
            url = "https://" + url
        if (dom := self._blocked(url)) is not None:
            return {"error": f"{dom} engelli alan adlari listesinde."}
        page = await self._ensure_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        return {**await self._state(page), "hint": "Etkilesim icin browser_snapshot cagir."}

    async def snapshot(self) -> dict[str, Any]:
        page = await self._ensure_page()
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        data = await page.evaluate(_SNAPSHOT_JS, MAX_ELEMENTS)
        lines = []
        for it in data["items"]:
            extra = ""
            if it.get("href"):
                extra += f" -> {it['href']}"
            if it.get("value"):
                extra += f" [deger: {it['value']}]"
            if it.get("options"):
                extra += f" secenekler: {', '.join(it['options'])}"
            if it.get("offscreen"):
                extra += " (asagida)"
            lines.append(f"[{it['ref']}] {it['kind']} \"{it['label']}\"{extra}")
        text = await page.evaluate("() => (document.body ? document.body.innerText : '')")
        text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
        return {
            **await self._state(page),
            "elements": "\n".join(lines),
            "element_count": data["total"],
            **({"note": f"Ilk {MAX_ELEMENTS} oge gosterildi; asagi kaydirip tekrar snapshot al."}
               if data["total"] > MAX_ELEMENTS else {}),
            "text": text[:1500],
        }

    async def click(self, ref: int) -> dict[str, Any]:
        loc = await self._element(ref)
        if (why := await self._guard(loc, "click")) is not None:
            return {"error": why, "blocked": True}
        page = await self._ensure_page()
        await loc.scroll_into_view_if_needed()
        await loc.click()
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        if (dom := self._blocked(page.url)) is not None:
            await page.go_back()
            return {"error": f"{dom} engelli; geri donuldu."}
        return {"status": "tiklandi", **await self._state(page)}

    async def type(self, ref: int, text: str, submit: bool = False) -> dict[str, Any]:
        loc = await self._element(ref)
        if (why := await self._guard(loc, "type")) is not None:
            return {"error": why, "blocked": True}
        await loc.scroll_into_view_if_needed()
        await loc.fill(text or "")
        page = await self._ensure_page()
        if submit:
            await loc.press("Enter")
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
        return {"status": "yazildi" + (" ve gonderildi" if submit else ""), **await self._state(page)}

    async def select(self, ref: int, value: str) -> dict[str, Any]:
        loc = await self._element(ref)
        if (why := await self._guard(loc, "type")) is not None:
            return {"error": why, "blocked": True}
        try:
            await loc.select_option(label=value)
        except Exception:  # noqa: BLE001 - etiket tutmazsa deger dene
            await loc.select_option(value=value)
        return {"status": f"secildi: {value}"}

    async def scroll(self, direction: str = "down") -> dict[str, Any]:
        page = await self._ensure_page()
        dy = {"up": -700, "top": -10**7, "bottom": 10**7}.get((direction or "down").lower(), 700)
        await page.mouse.wheel(0, dy)
        await page.wait_for_timeout(400)
        return {"status": f"kaydirildi: {direction}"}

    async def back(self) -> dict[str, Any]:
        page = await self._ensure_page()
        await page.go_back(wait_until="domcontentloaded")
        return await self._state(page)

    async def read(self, max_chars: int = DEFAULT_TEXT_CHARS) -> dict[str, Any]:
        page = await self._ensure_page()
        text = await page.evaluate("() => (document.body ? document.body.innerText : '')")
        text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
        limit = max(200, min(int(max_chars or DEFAULT_TEXT_CHARS), 20_000))
        return {**await self._state(page), "text": text[:limit], "truncated": len(text) > limit}

    async def screenshot(self) -> dict[str, Any]:
        page = await self._ensure_page()
        out_dir = APP_DIR / "data" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"browser_{datetime.now():%Y%m%d_%H%M%S}.png"
        await page.screenshot(path=str(path))
        return {"path": str(path), "hint": "Icerigi okumak icin ocr_image(path) kullan."}

    async def close(self) -> dict[str, Any]:
        await self.aclose()
        return {"status": "tarayici kapatildi"}


_session: BrowserSession | None = None


def get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session


def _run(method: str, *args: Any, timeout: float = SUBMIT_TIMEOUT_S) -> dict[str, Any]:
    session = get_session()
    worker = get_worker()
    if not session._registered:
        worker.on_shutdown(session.aclose)
        session._registered = True
    try:
        return worker.submit(getattr(session, method)(*args), timeout)
    except ImportError:
        return {"error": "playwright kurulu degil: `pip install playwright` + `playwright install chromium`."}
    except Exception as exc:  # noqa: BLE001 - tarayici hatasi ajani cokertmez
        logger.debug(f"[Tarayici] {method} hatasi: {exc!r}")
        msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        if "Executable doesn't exist" in str(exc):
            msg = "Chromium kurulu degil: `playwright install chromium` calistirin."
        return {"error": msg[:400]}


# ------------------------------------------------------------------ arac yuzleri

def browser_open(url: str) -> dict[str, Any]:
    """Kontrollu tarayicida bir web sayfasi acar (kalici profil; girisler hatirlanir)."""
    return _run("open", url)


def browser_snapshot() -> dict[str, Any]:
    """Acik sayfadaki tiklanabilir/yazilabilir ogeleri numarali (ref) listeler + sayfa metninin ozeti.
    Her tiklama/yazma oncesi ve sayfa degistikten sonra cagir."""
    return _run("snapshot")


def browser_click(ref: int) -> dict[str, Any]:
    """browser_snapshot'taki [ref] numarali ogeye tiklar (link, buton, sekme...)."""
    return _run("click", ref)


def browser_type(ref: int, text: str, submit: bool = False) -> dict[str, Any]:
    """[ref] numarali alana metin yazar (oncekini siler). submit=true ise Enter'a basar (arama kutulari icin)."""
    return _run("type", ref, text, submit)


def browser_select(ref: int, value: str) -> dict[str, Any]:
    """[ref] numarali acilir listede (select) bir secenegi etiketine gore secer."""
    return _run("select", ref, value)


def browser_scroll(direction: str = "down") -> dict[str, Any]:
    """Sayfayi kaydirir: down | up | top | bottom."""
    return _run("scroll", direction)


def browser_back() -> dict[str, Any]:
    """Tarayicida bir onceki sayfaya doner."""
    return _run("back")


def browser_read(max_chars: int = DEFAULT_TEXT_CHARS) -> dict[str, Any]:
    """Acik sayfanin gorunen metnini okur (en fazla max_chars karakter)."""
    return _run("read", max_chars)


def browser_screenshot() -> dict[str, Any]:
    """Acik sayfanin ekran goruntusunu data/screenshots altina kaydeder."""
    return _run("screenshot")


def browser_close() -> dict[str, Any]:
    """Kontrollu tarayiciyi kapatir."""
    return _run("close")


BROWSER_TOOLS = [browser_open, browser_snapshot, browser_click, browser_type, browser_select,
                 browser_scroll, browser_back, browser_read, browser_screenshot, browser_close]
