// El Kontrolu: havuzlanmis parcacik sistemi (typed array, hazir isik sprite'lari, Canvas2D).
// Hicbir gorsel dosya yok: sprite'lar acilista radyal gradyanla uretilir.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});

  const spriteCache = new Map();
  function sprite(color) {
    let c = spriteCache.get(color);
    if (c) return c;
    c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d");
    const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,1)");
    grd.addColorStop(0.18, color);
    grd.addColorStop(0.5, hexA(color, 0.35));
    grd.addColorStop(1, hexA(color, 0));
    g.fillStyle = grd;
    g.fillRect(0, 0, 64, 64);
    spriteCache.set(color, c);
    return c;
  }

  function hexA(hex, a) {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  class Particles {
    constructor(max) {
      this.max = max || 800;
      const M = this.max;
      this.x = new Float32Array(M); this.y = new Float32Array(M);
      this.vx = new Float32Array(M); this.vy = new Float32Array(M);
      this.life = new Float32Array(M); this.maxLife = new Float32Array(M);
      this.size = new Float32Array(M); this.grow = new Float32Array(M);
      this.drag = new Float32Array(M); this.grav = new Float32Array(M);
      this.col = new Uint16Array(M);
      this.colors = [];
      this.colorIdx = new Map();
      this.n = 0;
      this.quality = 1; // kare suresi uzayinca el-app dusurur
    }

    _color(c) {
      let i = this.colorIdx.get(c);
      if (i === undefined) { i = this.colors.length; this.colors.push(c); this.colorIdx.set(c, i); }
      return i;
    }

    // o: {vx, vy, life (s), size (px), grow (px/s), drag (0-1/s), grav (px/s2), color}
    emit(x, y, o) {
      if (this.quality < 1 && Math.random() > this.quality) return;
      if (this.n >= this.max) return;
      const i = this.n++;
      this.x[i] = x; this.y[i] = y;
      this.vx[i] = o.vx || 0; this.vy[i] = o.vy || 0;
      this.life[i] = this.maxLife[i] = o.life || 0.8;
      this.size[i] = o.size || 10; this.grow[i] = o.grow || 0;
      this.drag[i] = o.drag === undefined ? 1.5 : o.drag;
      this.grav[i] = o.grav || 0;
      this.col[i] = this._color(o.color || "#ff8c42");
    }

    update(dt) {
      let i = 0;
      while (i < this.n) {
        this.life[i] -= dt;
        if (this.life[i] <= 0) { this._kill(i); continue; }
        const d = Math.max(0, 1 - this.drag[i] * dt);
        this.vx[i] *= d; this.vy[i] = this.vy[i] * d + this.grav[i] * dt;
        this.x[i] += this.vx[i] * dt; this.y[i] += this.vy[i] * dt;
        this.size[i] = Math.max(0.5, this.size[i] + this.grow[i] * dt);
        i++;
      }
    }

    _kill(i) {
      const j = --this.n;
      if (i === j) return;
      this.x[i] = this.x[j]; this.y[i] = this.y[j]; this.vx[i] = this.vx[j]; this.vy[i] = this.vy[j];
      this.life[i] = this.life[j]; this.maxLife[i] = this.maxLife[j]; this.size[i] = this.size[j];
      this.grow[i] = this.grow[j]; this.drag[i] = this.drag[j]; this.grav[i] = this.grav[j]; this.col[i] = this.col[j];
    }

    draw(ctx) {
      if (!this.n) return;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (let i = 0; i < this.n; i++) {
        const a = this.life[i] / this.maxLife[i];
        const s = this.size[i];
        ctx.globalAlpha = Math.min(1, a * 1.4);
        ctx.drawImage(sprite(this.colors[this.col[i]]), this.x[i] - s, this.y[i] - s, s * 2, s * 2);
      }
      ctx.restore();
    }

    clear() { this.n = 0; }
  }

  JEL.sprite = sprite;
  JEL.hexA = hexA;
  JEL.Particles = Particles;
  JEL.rand = (a, b) => a + Math.random() * (b - a);
})();
