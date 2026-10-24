// El Kontrolu: acik elde avuc ve parmak uclari alev alir, parmaklar arasinda kivilcim atar.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});
  const FIRE = ["#ffd27a", "#ffb04a", "#ff8c42", "#ff5a1f", "#ff3d14"];

  class Fire {
    constructor(particles) {
      this.p = particles;
      this._sparks = []; // {a, b, life}
      this.intensity = 0; // ses icin (0-1)
    }

    // hand: {lm (ekran px), f (features)}; dt sn
    feed(hand, dt) {
      const r = JEL.rand, f = hand.f, lm = hand.lm;
      const s = f.size;
      const rate = 60 * dt; // kare basina kabaca
      // avuc
      for (let k = 0; k < rate * 2.2; k++) {
        this.p.emit(f.palm.x + r(-0.35, 0.35) * s, f.palm.y + r(-0.3, 0.3) * s, {
          vx: r(-25, 25), vy: r(-170, -70) * (s / 120), life: r(0.35, 0.8), size: r(0.1, 0.2) * s,
          grow: -s * 0.12, drag: 1.2, color: FIRE[(Math.random() * FIRE.length) | 0],
        });
      }
      // parmak uclari
      for (const ti of [4, 8, 12, 16, 20]) {
        const t = lm[ti];
        for (let k = 0; k < rate * 0.9; k++) {
          this.p.emit(t.x + r(-4, 4), t.y + r(-4, 4), {
            vx: r(-15, 15), vy: r(-120, -50) * (s / 120), life: r(0.25, 0.55), size: r(0.05, 0.11) * s,
            grow: -s * 0.08, drag: 1, color: FIRE[(Math.random() * 3) | 0],
          });
        }
      }
      // parmaklar arasi kivilcim (komsu uclar arasinda kisa zikzak)
      if (Math.random() < dt * 3.2) {
        const pairs = [[8, 12], [12, 16], [16, 20], [4, 8]];
        const [a, b] = pairs[(Math.random() * pairs.length) | 0];
        this._sparks.push({ a: { x: lm[a].x, y: lm[a].y }, b: { x: lm[b].x, y: lm[b].y }, life: 0.12, seed: Math.random() });
        for (let k = 0; k < 6; k++) {
          this.p.emit((lm[a].x + lm[b].x) / 2, (lm[a].y + lm[b].y) / 2, {
            vx: r(-160, 160), vy: r(-160, 60), life: r(0.15, 0.35), size: r(2, 4), drag: 2, grav: 300, color: "#fff2c0",
          });
        }
      }
      this.intensity = Math.min(1, this.intensity + dt * 3);
    }

    update(dt) {
      this.intensity = Math.max(0, this.intensity - dt * 1.5);
      this._sparks = this._sparks.filter((s) => (s.life -= dt) > 0);
    }

    draw(ctx) {
      if (!this._sparks.length) return;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.strokeStyle = "#fff2c0";
      ctx.shadowColor = "#ff8c42";
      ctx.shadowBlur = 10;
      ctx.lineWidth = 1.6;
      for (const s of this._sparks) {
        ctx.globalAlpha = s.life / 0.12;
        ctx.beginPath();
        ctx.moveTo(s.a.x, s.a.y);
        for (let i = 1; i < 6; i++) {
          const t = i / 6;
          const jx = (Math.sin(s.seed * 99 + i * 7.3) * 7), jy = (Math.cos(s.seed * 51 + i * 3.1) * 7);
          ctx.lineTo(s.a.x + (s.b.x - s.a.x) * t + jx, s.a.y + (s.b.y - s.a.y) * t + jy);
        }
        ctx.lineTo(s.b.x, s.b.y);
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  JEL.Fire = Fire;
  JEL.FIRE_COLORS = FIRE;
})();
