// El Kontrolu: iki acik avucun onunde donen turuncu muhur halkalari.
// Eli yana cevirince (avuc genisligi azalinca) halka da perspektifle daralir.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});
  const RUNES = "ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ";

  class Seal {
    constructor() {
      this.seals = new Map(); // hand id -> {x, y, r, roll, facing, alpha, born}
    }

    feed(id, hand, t) {
      const f = hand.f;
      const target = { x: f.palm.x, y: f.palm.y - f.size * 0.15, r: f.size * 1.25, roll: f.roll, facing: f.facing };
      let s = this.seals.get(id);
      if (!s) { s = Object.assign({ alpha: 0, born: t, seen: t }, target); this.seals.set(id, s); }
      const k = 0.35;
      s.x += (target.x - s.x) * k; s.y += (target.y - s.y) * k; s.r += (target.r - s.r) * k;
      s.roll += angleDiff(target.roll, s.roll) * k; s.facing += (target.facing - s.facing) * k;
      s.seen = t;
    }

    update(dt, t) {
      for (const [id, s] of this.seals) {
        const alive = t - s.seen < 80;
        s.alpha = Math.max(0, Math.min(1, s.alpha + (alive ? dt * 4 : -dt * 3)));
        if (!alive && s.alpha <= 0) this.seals.delete(id);
      }
    }

    draw(ctx, t) {
      for (const s of this.seals.values()) {
        if (s.alpha <= 0) continue;
        const open = Math.min(1, (t - s.born) / 450); // acilis animasyonu
        const R = s.r * (0.4 + 0.6 * easeOut(open));
        ctx.save();
        ctx.translate(s.x, s.y);
        ctx.rotate(s.roll);
        ctx.scale(Math.max(0.12, s.facing), 1);
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = s.alpha * 0.95;
        ctx.shadowColor = "#ff8c42";
        ctx.shadowBlur = 18;
        const rot = t / 1000;
        ring(ctx, R, 2.4, "#ff9a4a");
        ring(ctx, R * 0.93, 1, "#ffcf8a");
        ticks(ctx, R * 0.93, R * 0.86, 72, rot * 0.6, "#ffb46a");
        runes(ctx, R * 0.78, rot * -0.45, "#ffd9a8", R * 0.09);
        ring(ctx, R * 0.68, 1.6, "#ff8c42");
        star(ctx, R * 0.66, 6, rot * 0.8, "#ff7a2e");
        star(ctx, R * 0.66, 6, -rot * 0.8 + Math.PI / 6, "#ffb46a");
        ring(ctx, R * 0.36, 1.2, "#ffcf8a");
        ticks(ctx, R * 0.36, R * 0.3, 24, -rot * 1.4, "#ffcf8a");
        ctx.restore();
      }
    }

    clear() { this.seals.clear(); }
  }

  function angleDiff(a, b) { let d = a - b; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function ring(ctx, r, w, c) { ctx.strokeStyle = c; ctx.lineWidth = w; ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.stroke(); }
  function ticks(ctx, r0, r1, n, rot, c) {
    ctx.strokeStyle = c; ctx.lineWidth = 1.2; ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const a = rot + (i / n) * Math.PI * 2, rr = i % 6 === 0 ? r1 - (r0 - r1) : r1;
      ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0); ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
    }
    ctx.stroke();
  }
  function runes(ctx, r, rot, c, size) {
    ctx.fillStyle = c; ctx.font = `${Math.max(8, size)}px serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const n = 18;
    for (let i = 0; i < n; i++) {
      const a = rot + (i / n) * Math.PI * 2;
      ctx.save(); ctx.translate(Math.cos(a) * r, Math.sin(a) * r); ctx.rotate(a + Math.PI / 2);
      ctx.fillText(RUNES[i % RUNES.length], 0, 0); ctx.restore();
    }
  }
  function star(ctx, r, n, rot, c) {
    ctx.strokeStyle = c; ctx.lineWidth = 1.3; ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const a = rot + (i / n) * Math.PI * 2;
      const x = Math.cos(a) * r, y = Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath(); ctx.stroke();
  }

  JEL.Seal = Seal;
})();
