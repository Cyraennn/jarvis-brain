// El Kontrolu: el ozelliklerinden durus (poz) siniflandirma + histerezis + hareket olaylari.
// Duruslar: open (acik el) · fist (yumruk) · pinch (cimdik) · point (isaret) ·
//           thumbs_up (basparmak) · victory (zafer) · none
// Olaylar : burst (yumruk -> hizla acik el), swipe_left / swipe_right (acik avuc savurma),
//           push (acik avucu kameraya/ileri itme)
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.CyraenPoses = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const CONFIG = {
    pinchEnter: 0.30,   // basparmak-isaret mesafesi / el boyu: bunun altinda cimdik basla
    pinchExit: 0.44,    // ... bunun ustunde cimdik bitir (histerezis)
    stableFrames: 3,    // yeni durus bu kadar ardisik karede gorulunce gecerli olur
    burstMaxMs: 320,    // yumruktan acik ele en fazla bu surede gecilirse "patlat"
    burstMinFistMs: 140,
    swipeSpeed: 1.9,    // el boyu / saniye
    swipeCooldownMs: 650,
    pushRate: 0.9,      // el boyunun buyume orani / saniye (kameraya itme)
    pushCooldownMs: 900,
  };

  // Ozelliklerden ham (histerezissiz) durus. `wasPinch`: cimdik histerezisi icin onceki durum.
  function rawPose(f, wasPinch) {
    const e = f.ext;
    const curled = (v) => v < 0.35;
    const open = (v) => v > 0.6;
    const pinchTh = wasPinch ? CONFIG.pinchExit : CONFIG.pinchEnter;
    // cimdik: uclar yakin VE el yumruk degil (yumrukta da uclar yakin olabilir)
    const othersOpen = [e.middle, e.ring, e.pinky].filter((v) => !curled(v)).length;
    if (f.pinch < pinchTh && (othersOpen >= 1 || e.index > 0.2)) return "pinch";
    const others = [e.middle, e.ring, e.pinky];
    if (open(e.index) && open(e.middle) && curled(e.ring) && curled(e.pinky)) return "victory";
    if (open(e.index) && others.every(curled) && e.thumb < 0.75) return "point";
    if (e.thumb > 0.55 && f.thumbUp > 0.45 && curled(e.index) && others.every(curled)) return "thumbs_up";
    if ([e.index, ...others].every(curled)) return "fist";
    if ([e.index, ...others].filter(open).length >= 4) return "open";
    return "none";
  }

  // Bir elin zaman icindeki durumu.
  class PoseTracker {
    constructor(config) {
      this.cfg = Object.assign({}, CONFIG, config || {});
      this.pose = "none";
      this.since = 0;
      this._cand = "none";
      this._candCount = 0;
      this._fistStart = null;
      this._fistEnd = null;
      this._hist = []; // {t, x, y, size}
      this._lastSwipe = -1e9;
      this._lastPush = -1e9;
    }

    // f: features(lm), t: ms. -> {pose, changed, events: [...], velocity}
    update(f, t) {
      const events = [];
      const raw = rawPose(f, this.pose === "pinch");
      if (raw === this._cand) this._candCount++;
      else { this._cand = raw; this._candCount = 1; }
      const prev = this.pose;
      let changed = false;
      // cimdik ve yumruk aninda tepki versin (1 kare), digerleri kararli olsun
      const need = raw === "pinch" || prev === "pinch" ? 2 : this.cfg.stableFrames;
      if (this._cand !== this.pose && this._candCount >= need) {
        this.pose = this._cand;
        this.since = t;
        changed = true;
      }
      // yumruk -> acik: patlatma
      if (changed && prev === "fist") this._fistEnd = t;
      if (changed && this.pose === "fist") this._fistStart = t;
      if (changed && this.pose === "open" && this._fistStart !== null && this._fistEnd !== null) {
        const fistMs = this._fistEnd - this._fistStart;
        if (t - this._fistEnd <= this.cfg.burstMaxMs && fistMs >= this.cfg.burstMinFistMs) {
          events.push({ type: "burst", x: f.palm.x, y: f.palm.y });
        }
        this._fistStart = null;
      }
      // hiz gecmisi (son ~250 ms)
      this._hist.push({ t, x: f.palm.x, y: f.palm.y, size: f.size });
      while (this._hist.length > 2 && t - this._hist[0].t > 250) this._hist.shift();
      const v = this.velocity();
      if (this.pose === "open") {
        if (Math.abs(v.vx) > this.cfg.swipeSpeed && Math.abs(v.vx) > Math.abs(v.vy) * 1.6
            && t - this._lastSwipe > this.cfg.swipeCooldownMs) {
          // ekran (ayna) uzayinda: sola savurma = vx < 0
          events.push({ type: v.vx < 0 ? "swipe_left" : "swipe_right" });
          this._lastSwipe = t;
        }
        if (v.grow > this.cfg.pushRate && t - this._lastPush > this.cfg.pushCooldownMs) {
          events.push({ type: "push" });
          this._lastPush = t;
        }
      }
      return { pose: this.pose, changed, prev, events, velocity: v, heldMs: t - this.since };
    }

    // el boyu / saniye cinsinden hiz; grow: boyun goreli buyume hizi (kameraya yaklasma)
    velocity() {
      const h = this._hist;
      if (h.length < 2) return { vx: 0, vy: 0, px: 0, py: 0, grow: 0 };
      const a = h[0], b = h[h.length - 1];
      const dt = Math.max(1, b.t - a.t) / 1000;
      const s = (a.size + b.size) / 2;
      return {
        vx: (b.x - a.x) / s / dt, vy: (b.y - a.y) / s / dt,
        px: (b.x - a.x) / dt, py: (b.y - a.y) / dt,   // piksel / saniye (firlatma icin)
        grow: (b.size - a.size) / a.size / dt,
      };
    }
  }

  return { CONFIG, rawPose, PoseTracker };
});
