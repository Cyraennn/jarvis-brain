// El Kontrolu: avuctan enerji dalgasi + ekran sarsintisi; simsek; isik izi.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});

  class Burst {
    constructor(particles) {
      this.p = particles;
      this.waves = [];
      this.shake = 0;
    }

    wave(x, y, size) {
      this.waves.push({ x, y, r: size * 0.3, max: size * 6, t: 0 });
      for (let i = 0; i < 90; i++) {
        const a = Math.random() * Math.PI * 2, sp = 300 + Math.random() * 900;
        this.p.emit(x, y, { vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 0.4 + Math.random() * 0.5,
          size: 3 + Math.random() * 8, drag: 2.5, color: Math.random() < 0.5 ? "#7ff3ff" : "#ffcf8a" });
      }
      this.kick(1);
    }

    kick(amount) { this.shake = Math.min(1.5, this.shake + amount); }

    update(dt) {
      this.shake = Math.max(0, this.shake - dt * 2.8);
      for (const w of this.waves) { w.t += dt; w.r += (w.max - w.r) * Math.min(1, dt * 5); }
      this.waves = this.waves.filter((w) => w.t < 0.7);
    }

    // ekran sarsintisi kaymasi (px)
    offset() {
      if (this.shake <= 0) return [0, 0];
      const m = this.shake * 14;
      return [(Math.random() - 0.5) * m, (Math.random() - 0.5) * m];
    }

    draw(ctx) {
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (const w of this.waves) {
        const a = 1 - w.t / 0.7;
        ctx.globalAlpha = a;
        ctx.lineWidth = 10 * a + 1;
        ctx.strokeStyle = "#7ff3ff";
        ctx.shadowColor = "#34e3f0"; ctx.shadowBlur = 24;
        ctx.beginPath(); ctx.arc(w.x, w.y, w.r, 0, Math.PI * 2); ctx.stroke();
        ctx.lineWidth = 3 * a; ctx.strokeStyle = "#ffcf8a";
        ctx.beginPath(); ctx.arc(w.x, w.y, w.r * 0.8, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.restore();
    }
  }

  // Iki isaret parmagi ucu arasinda simsek (orta nokta kaydirmali, dallanan)
  class Lightning {
    constructor(particles) { this.p = particles; this.bolts = []; this._t = 0; this.active = false; }

    feed(a, b, dt) {
      this.active = true;
      this._t -= dt;
      if (this._t > 0) return;
      this._t = 0.045;
      const d = Math.hypot(b.x - a.x, b.y - a.y);
      this.bolts = [{ pts: bolt(a, b, d * 0.22, 6), w: 2.4, life: 0.09 }];
      if (Math.random() < 0.6) {
        const main = this.bolts[0].pts, k = main[(main.length * (0.3 + Math.random() * 0.4)) | 0];
        const ang = Math.atan2(b.y - a.y, b.x - a.x) + (Math.random() - 0.5) * 1.6;
        const end = { x: k.x + Math.cos(ang) * d * 0.3, y: k.y + Math.sin(ang) * d * 0.3 };
        this.bolts.push({ pts: bolt(k, end, d * 0.1, 4), w: 1.2, life: 0.07 });
      }
      for (const end of [a, b]) {
        this.p.emit(end.x, end.y, { vx: (Math.random() - 0.5) * 200, vy: (Math.random() - 0.5) * 200,
          life: 0.2, size: 10, drag: 3, color: "#a8f6ff" });
      }
    }

    update(dt) {
      for (const bl of this.bolts) bl.life -= dt;
      this.bolts = this.bolts.filter((bl) => bl.life > 0);
      if (!this.bolts.length) this.active = false;
    }

    draw(ctx) {
      if (!this.bolts.length) return;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      for (const bl of this.bolts) {
        for (const [w, c, blur] of [[bl.w * 5, "rgba(80,200,255,0.25)", 0], [bl.w * 2, "#9fefff", 16], [bl.w * 0.8, "#ffffff", 0]]) {
          ctx.lineWidth = w; ctx.strokeStyle = c; ctx.shadowColor = "#34e3f0"; ctx.shadowBlur = blur;
          ctx.beginPath();
          bl.pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
          ctx.stroke();
        }
      }
      ctx.restore();
    }
  }

  function bolt(a, b, disp, depth) {
    let pts = [a, b];
    let d = disp;
    for (let k = 0; k < depth; k++) {
      const next = [pts[0]];
      for (let i = 0; i < pts.length - 1; i++) {
        const p = pts[i], q = pts[i + 1];
        const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
        const nx = -(q.y - p.y), ny = q.x - p.x, nl = Math.hypot(nx, ny) || 1;
        const off = (Math.random() - 0.5) * d;
        next.push({ x: mx + (nx / nl) * off, y: my + (ny / nl) * off }, q);
      }
      pts = next;
      d *= 0.55;
    }
    return pts;
  }

  // Tek isaret parmagi ucu havada isik izi birakir
  class Trail {
    constructor() { this.pts = []; }
    feed(p, t) {
      const last = this.pts[this.pts.length - 1];
      if (!last || Math.hypot(p.x - last.x, p.y - last.y) > 2) this.pts.push({ x: p.x, y: p.y, t });
    }
    update(t) { while (this.pts.length && t - this.pts[0].t > 900) this.pts.shift(); }
    draw(ctx, t) {
      if (this.pts.length < 2) return;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      for (let i = 1; i < this.pts.length; i++) {
        const a = this.pts[i - 1], b = this.pts[i];
        const age = 1 - (t - b.t) / 900;
        if (age <= 0) continue;
        ctx.globalAlpha = age;
        ctx.strokeStyle = "#ff9a4a"; ctx.lineWidth = 9 * age;
        ctx.shadowColor = "#ff8c42"; ctx.shadowBlur = 14;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        ctx.strokeStyle = "#fff4e0"; ctx.lineWidth = 2.5 * age; ctx.shadowBlur = 0;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      ctx.restore();
    }
    clear() { this.pts = []; }
  }

  JEL.Burst = Burst;
  JEL.Lightning = Lightning;
  JEL.Trail = Trail;
})();
