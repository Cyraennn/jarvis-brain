// Kitaplik koordinat kurali (TEK KAYNAK, Node'da test edilir):
//   - Kutular aynalanmamis HAM kamera karesinde 0-1: {x, y, w, h}  (server/data/kitaplik.json)
//   - Ekranda goruntu aynalanir: ayna x = 1 - x - w
//   - Video `object-fit: cover` ile tam ekrana yayilir: olcek + kayma (T) hesaba katilir
//   - Kirpma (drawImage) HAM kutuyla yapilir; isabet testi ekran pikselinde.
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.CyraenShelfGeom = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // video (vw x vh) -> gorunum (W x H), object-fit: cover
  function coverTransform(vw, vh, W, H) {
    const s = Math.max(W / Math.max(1, vw), H / Math.max(1, vh));
    return { s, ox: (W - vw * s) / 2, oy: (H - vh * s) / 2, vw, vh, W, H };
  }

  // ham normalize nokta -> ekran pikseli (aynali)
  function rawToScreen(T, rx, ry) {
    return { x: T.ox + (1 - rx) * T.vw * T.s, y: T.oy + ry * T.vh * T.s };
  }

  // ekran pikseli -> ham normalize nokta
  function screenToRaw(T, x, y) {
    return { x: 1 - (x - T.ox) / (T.vw * T.s), y: (y - T.oy) / (T.vh * T.s) };
  }

  // ham kutu -> ekran dikdortgeni (piksel, aynali)
  function boxToScreen(T, b) {
    const p = rawToScreen(T, b.x + b.w, b.y); // aynada sol kenar = ham sag kenar
    return { x: p.x, y: p.y, w: b.w * T.vw * T.s, h: b.h * T.vh * T.s };
  }

  // ekran dikdortgeni -> ham kutu
  function screenRectToBox(T, r) {
    const x0 = Math.min(r.x, r.x + r.w), x1 = Math.max(r.x, r.x + r.w);
    const y0 = Math.min(r.y, r.y + r.h), y1 = Math.max(r.y, r.y + r.h);
    const a = screenToRaw(T, x1, y0), b = screenToRaw(T, x0, y1);
    return clampBox({ x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y });
  }

  function clampBox(b) {
    const x0 = Math.max(0, Math.min(1, b.x)), y0 = Math.max(0, Math.min(1, b.y));
    const x1 = Math.max(0, Math.min(1, b.x + b.w)), y1 = Math.max(0, Math.min(1, b.y + b.h));
    if (x1 - x0 < 0.002 || y1 - y0 < 0.002) return null;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  // drawImage icin kaynak piksel dikdortgeni (HAM kare; ayna yok)
  function cropRect(b, vw, vh) {
    const sx = Math.max(0, Math.floor(b.x * vw)), sy = Math.max(0, Math.floor(b.y * vh));
    const sw = Math.max(1, Math.min(vw - sx, Math.ceil(b.w * vw)));
    const sh = Math.max(1, Math.min(vh - sy, Math.ceil(b.h * vh)));
    return { sx, sy, sw, sh };
  }

  // nokta ekran bolgesinde mi (kenar payi px)
  function inRect(r, p, margin) {
    const m = margin || 0;
    return p.x >= r.x - m && p.x <= r.x + r.w + m && p.y >= r.y - m && p.y <= r.y + r.h + m;
  }

  // Parmak ucu hizasindaki sirt puani (kucuk = iyi). Dikeyde sirtin boyu icindeyse yalniz
  // yatay uzaklik sayilir: uc tam ustunde olmak zorunda degil.
  function spineScore(rect, p) {
    const cx = rect.x + rect.w / 2;
    const dx = Math.max(0, Math.abs(p.x - cx) - rect.w / 2) + Math.abs(p.x - cx) * 0.15;
    const dy = p.y < rect.y ? rect.y - p.y : p.y > rect.y + rect.h ? p.y - (rect.y + rect.h) : 0;
    return dx + dy * 2.2;
  }

  // En yakin sirt + histerezis: mevcut secimden ayrilmak icin aday belirgin daha yakin olmali.
  // items: [{id, rect}] (ekran) ; opts: {current, maxDist, switchMargin}
  function pickSpine(items, p, opts) {
    const o = opts || {};
    const maxDist = o.maxDist === undefined ? 60 : o.maxDist;
    let best = null, bestS = Infinity, cur = null, curS = Infinity;
    for (const it of items) {
      const s = spineScore(it.rect, p);
      if (s < bestS) { best = it; bestS = s; }
      if (o.current && it.id === o.current) { cur = it; curS = s; }
    }
    if (cur && curS <= maxDist * 1.4) {
      const margin = o.switchMargin === undefined ? Math.max(10, cur.rect.w * 0.45) : o.switchMargin;
      if (!best || best === cur || bestS > curS - margin) return { item: cur, score: curS };
    }
    if (!best || bestS > maxDist) return { item: null, score: Infinity };
    return { item: best, score: bestS };
  }

  // Kutularin kapsadigi ekran bolgesi
  function unionRect(rects, pad) {
    if (!rects.length) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const r of rects) {
      x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y);
      x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.h);
    }
    const p = pad || 0;
    return { x: x0 - p, y: y0 - p, w: x1 - x0 + 2 * p, h: y1 - y0 + 2 * p };
  }

  return { coverTransform, rawToScreen, screenToRaw, boxToScreen, screenRectToBox, clampBox,
    cropRect, inRect, spineScore, pickSpine, unionRect };
});
