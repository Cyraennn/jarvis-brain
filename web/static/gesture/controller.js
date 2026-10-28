// El Kontrolu: basili tutma kontrolleri (halka dolunca calisir).
//
// KONTROLLER dizisine bir satir ekleyerek yeni komut tanimlanir:
//   { jest: "thumbs_up", sure: 1000, ad: "Türk kahvesi",
//     eylem: { tip: "komut", metin: "Jarvis, ..." } }      -> Jarvis'e sesli komut gibi gider
//   { ..., eylem: { tip: "kontrol", action: "interrupt" } } -> /api/control
//   kosul: "speaking"  -> yalnizca Jarvis konusurken
// Jestler: thumbs_up · victory · fist · open · point (poses.js)
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.JarvisController = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const KONTROLLER = [
    { jest: "thumbs_up", sure: 1000, ad: "Türk kahvesi",
      eylem: { tip: "komut", metin: "Jarvis, bana bol köpüklü bir Türk kahvesi yap" } },
    { jest: "victory", sure: 900, ad: "Salon ışığı",
      eylem: { tip: "komut", metin: "Jarvis, salon ışığını aç ya da kapat" } },
    { jest: "fist", sure: 1800, ad: "Sustur", kosul: "speaking",
      eylem: { tip: "kontrol", action: "interrupt" } },
  ];

  const COOLDOWN_MS = 2500;   // ayni kontrol tekrar tetiklenmeden once
  const GRACE_MS = 120;       // takip bir an kopsa da halka sifirlanmasin

  // Kurallar: [{jest, sure, eylem, kosul?, ad?}] -> her karede update(hands, ctx, t)
  // hands: [{id, pose, x, y}] ; ctx: {speaking, thinking, disabled:Set<jest>}
  // -> {rings: [{id, x, y, progress, rule}], fired: [{rule, hand}]}
  class HoldController {
    constructor(rules, opts) {
      this.rules = rules || KONTROLLER;
      this.cooldownMs = (opts && opts.cooldownMs) || COOLDOWN_MS;
      this._holds = new Map();     // hand id -> {jest, start, lastSeen, fired}
      this._lastFire = new Map();  // rule index -> t
    }

    reset() { this._holds.clear(); }

    _ruleFor(pose, ctx) {
      for (let i = 0; i < this.rules.length; i++) {
        const r = this.rules[i];
        if (r.jest !== pose) continue;
        if (ctx && ctx.disabled && ctx.disabled.has(r.jest)) continue;
        if (r.kosul === "speaking" && !(ctx && ctx.speaking)) continue;
        return i;
      }
      return -1;
    }

    update(hands, ctx, t) {
      const rings = [], fired = [];
      const seen = new Set();
      for (const h of hands) {
        seen.add(h.id);
        const ri = this._ruleFor(h.pose, ctx);
        let st = this._holds.get(h.id);
        if (ri < 0) {
          if (st && t - st.lastSeen > GRACE_MS) this._holds.delete(h.id);
          else if (st && st.rule !== undefined && h.pose !== this.rules[st.rule].jest) this._holds.delete(h.id);
          continue;
        }
        if (!st || st.rule !== ri) {
          st = { rule: ri, start: t, lastSeen: t, fired: false };
          this._holds.set(h.id, st);
        }
        st.lastSeen = t;
        const rule = this.rules[ri];
        const cooling = t - (this._lastFire.get(ri) || -1e12) < this.cooldownMs;
        const progress = cooling ? 0 : Math.min(1, (t - st.start) / rule.sure);
        if (!st.fired && !cooling && progress >= 1) {
          st.fired = true;
          this._lastFire.set(ri, t);
          fired.push({ rule, hand: h });
        }
        if (!st.fired && !cooling && t - st.start > 120) {
          rings.push({ id: h.id, x: h.x, y: h.y, progress, rule });
        }
      }
      for (const [id, st] of this._holds) {
        if (!seen.has(id) && t - st.lastSeen > GRACE_MS) this._holds.delete(id);
      }
      return { rings, fired };
    }
  }

  return { KONTROLLER, HoldController, COOLDOWN_MS };
});
