// El Kontrolu: kamera kipirdadi mi? Kurulumda rafin 32x24 gri resmi saklanir; 3 sn'de bir
// karsilastirilir. Genel kayma/donme/yakinlasma uyari verir; onden gecen biri (yerel degisim),
// isik degisimi (normalizasyon) ve goruntu gurultusu vermez.
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else { root.CyraenShelfDrift = factory(); (root.JEL = root.JEL || {}).Drift = root.CyraenShelfDrift; }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const W = 32, H = 24, MAXS = 3;

  function normalize(gray) {
    let m = 0;
    for (const v of gray) m += v;
    m /= gray.length;
    let sd = 0;
    for (const v of gray) sd += (v - m) * (v - m);
    sd = Math.sqrt(sd / gray.length) || 1;
    return Float32Array.from(gray, (v) => (v - m) / sd);
  }

  // kaydirilmis karsilastirma hatasi: ortusen piksellerin EN DUSUK %60'inin ortalamasi
  function shiftError(a, b, dx, dy) {
    const errs = [];
    for (let y = Math.max(0, dy); y < Math.min(H, H + dy); y++) {
      for (let x = Math.max(0, dx); x < Math.min(W, W + dx); x++) {
        errs.push(Math.abs(a[y * W + x] - b[(y - dy) * W + (x - dx)]));
      }
    }
    errs.sort((p, q) => p - q);
    const n = Math.max(1, Math.floor(errs.length * 0.6));
    let s = 0;
    for (let i = 0; i < n; i++) s += errs[i];
    return s / n;
  }

  // -> {moved: bool, shift: [dx, dy], err0, best}
  function compare(refGray, curGray) {
    const a = normalize(refGray), b = normalize(curGray);
    const e0 = shiftError(a, b, 0, 0);
    let best = e0, bx = 0, by = 0;
    for (let dy = -MAXS; dy <= MAXS; dy++) {
      for (let dx = -MAXS; dx <= MAXS; dx++) {
        if (!dx && !dy) continue;
        const e = shiftError(a, b, dx, dy);
        if (e < best) { best = e; bx = dx; by = dy; }
      }
    }
    const shifted = (Math.abs(bx) >= 2 || Math.abs(by) >= 2) && best < e0 * 0.7;
    const changed = best > 0.42; // donme/yakinlasma: hicbir kaydirma oturmuyor
    return { moved: shifted || changed, shift: [bx, by], err0: e0, best };
  }

  // tarayicida: kaynaktan (video/canvas) 32x24 gri dizi
  let _cv = null;
  function thumb(source) {
    if (!_cv) {
      _cv = typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(W, H) : document.createElement("canvas");
      _cv.width = W; _cv.height = H;
    }
    const g = _cv.getContext("2d", { willReadFrequently: true });
    g.drawImage(source, 0, 0, W, H);
    const d = g.getImageData(0, 0, W, H).data;
    const out = new Array(W * H);
    for (let i = 0; i < W * H; i++) out[i] = Math.round(d[i * 4] * 0.299 + d[i * 4 + 1] * 0.587 + d[i * 4 + 2] * 0.114);
    return out;
  }

  // 3 sn'de bir kontrol; art arda 2 tespit uyari yakar, 1 temiz sonuc soner
  class DriftWatch {
    constructor() { this.ref = null; this.hits = 0; this.warn = false; this.last = 0; this.forced = false; }
    setReference(ref) { this.ref = ref && ref.gri ? ref.gri : ref; this.hits = 0; this.warn = false; this.forced = false; }
    check(source, t) {
      if (!this.ref || t - this.last < 3000) return this.warn;
      this.last = t;
      let res;
      try { res = compare(this.ref, thumb(source)); } catch (e) { return this.warn; }
      this.hits = res.moved ? this.hits + 1 : 0;
      this.warn = this.forced || this.hits >= 2;
      return this.warn;
    }
  }

  return { W, H, normalize, compare, thumb, DriftWatch };
});
