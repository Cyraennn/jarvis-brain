// El Kontrolu: parcacik gezegenleri (Saturn, Dunya, Mars, Jupiter, Ay, Gunes).
// Cimdikte parmak uclarinda toplanir, elle tasinir, el cevrilince Saturn'un halkasi egilir,
// birakinca suzulur / savrulursa firlar, yumruk -> acik el ile kendi renklerinde patlar.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});

  const KINDS = ["saturn", "dunya", "mars", "jupiter", "ay", "gunes"];
  const NAMES = { saturn: "SATÜRN", dunya: "DÜNYA", mars: "MARS", jupiter: "JÜPİTER", ay: "AY", gunes: "GÜNEŞ" };
  const SPHERE_N = 360, RING_N = 240;

  // ucuz, deterministik "gurultu" (kure uzerinde kesintisiz)
  function noise(x, y, z) {
    return 0.5 + 0.25 * Math.sin(3.1 * x + 1.7 * y + 0.3) * Math.cos(2.7 * z - 1.1 * x + 1.9)
      + 0.15 * Math.sin(6.3 * y + 5.1 * z + 2.2) * Math.sin(7.7 * x + 0.5)
      + 0.1 * Math.sin(13.1 * z + 11.3 * x - 9.7 * y);
  }

  function colorFor(kind, x, y, z) {
    const lat = Math.asin(Math.max(-1, Math.min(1, y)));
    const n = noise(x, y, z);
    switch (kind) {
      case "saturn": {
        const b = Math.sin(lat * 14 + n * 1.5);
        return b > 0.4 ? "#f1dfb2" : b > -0.2 ? "#d8b77a" : "#b8925a";
      }
      case "jupiter": {
        // buyuk kirmizi leke
        if (Math.hypot(lat + 0.35, Math.atan2(z, x) - 0.6) < 0.22) return "#c4502c";
        const b = Math.sin(lat * 11 + n * 0.8);
        return b > 0.5 ? "#f3e2c4" : b > 0 ? "#d79a62" : b > -0.5 ? "#b7703f" : "#e6c79a";
      }
      case "dunya":
        if (Math.abs(lat) > 1.25) return "#f4f8ff";
        if (n > 0.72) return "#ffffff"; // bulut
        if (n > 0.56) return n > 0.64 ? "#8a7a46" : "#3f8f4a";
        return n > 0.45 ? "#2a6fd6" : "#1b4fa8";
      case "mars":
        if (Math.abs(lat) > 1.35) return "#f2e9e2";
        return n > 0.62 ? "#7a2a12" : n > 0.48 ? "#c4522a" : "#e07a42";
      case "ay":
        return n > 0.66 ? "#6f6f74" : n > 0.52 ? "#a4a4a8" : "#d2d2d4";
      case "gunes":
        return n > 0.64 ? "#ffffff" : n > 0.5 ? "#ffe27a" : n > 0.38 ? "#ffb23a" : "#ff7a1a";
      default:
        return "#ffffff";
    }
  }

  function fibSphere(n) {
    const pts = [], g = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), a = g * i;
      pts.push([Math.cos(a) * r, y, Math.sin(a) * r]);
    }
    return pts;
  }
  const SPHERE = fibSphere(SPHERE_N);

  class Planet {
    constructor(kind, x, y, radius) {
      this.id = Math.random().toString(36).slice(2, 8);
      this.x = x; this.y = y; this.vx = 0; this.vy = 0;
      this.R = radius; this.targetR = radius;
      this.tilt = 0.35; this.roll = 0;
      this.spin = Math.random() * 6;
      this.state = "forming"; this.stateT = 0;
      this.held = true;
      this.alpha = 1;
      this.bob = Math.random() * 6;
      const total = SPHERE_N + RING_N;
      this.px = new Float32Array(total); this.py = new Float32Array(total);
      this.pvx = new Float32Array(total); this.pvy = new Float32Array(total);
      for (let i = 0; i < total; i++) { // ilk konum: parmak ucunda kucuk bulut
        const a = Math.random() * Math.PI * 2, d = Math.random() * radius * 0.25;
        this.px[i] = x + Math.cos(a) * d; this.py[i] = y + Math.sin(a) * d;
      }
      this.setKind(kind);
    }

    setKind(kind) {
      this.kind = kind;
      this.colors = SPHERE.map(([x, y, z]) => colorFor(kind, x, y, z));
      this.ring = [];
      if (kind === "saturn") {
        for (let i = 0; i < RING_N; i++) {
          const rr = 1.35 + Math.random() * 0.95, a = Math.random() * Math.PI * 2;
          const gap = rr > 1.9 && rr < 1.98; // Cassini boslugu
          this.ring.push({ r: gap ? rr + 0.1 : rr, a, c: rr < 1.7 ? "#d9c49a" : rr < 2.0 ? "#bfa77e" : "#8f7d60" });
        }
      }
    }

    // Kure noktasi -> ekran (dondurulmus, egik, ortografik). -> [sx, sy, depth]
    project(p, i) {
      const [x0, y0, z0] = p;
      const cs = Math.cos(this.spin), sn = Math.sin(this.spin);
      let x = x0 * cs + z0 * sn, z = -x0 * sn + z0 * cs, y = y0;
      const ct = Math.cos(this.tilt), st = Math.sin(this.tilt);
      const y1 = y * ct - z * st, z1 = y * st + z * ct;
      const cr = Math.cos(this.roll), sr = Math.sin(this.roll);
      return [this.x + (x * cr - y1 * sr) * this.R, this.y + (x * sr + y1 * cr) * this.R, z1];
    }
  }

  class PlanetSystem {
    constructor(particles) {
      this.p = particles;
      this.planets = [];
      this.order = 0;
      this.onEvent = null; // (type, planet) -> ses vb.
    }

    nextKind(fixed) {
      if (fixed && KINDS.includes(fixed)) return fixed;
      const k = KINDS[this.order % KINDS.length];
      this.order++;
      return k;
    }

    spawn(kind, x, y, radius) {
      while (this.planets.length >= 3) this.planets.shift();
      const pl = new Planet(kind, x, y, radius);
      this.planets.push(pl);
      this.onEvent && this.onEvent("form", pl);
      return pl;
    }

    hold(pl, x, y, roll, radius) {
      pl.held = true;
      pl.x += (x - pl.x) * 0.55; pl.y += (y - pl.y) * 0.55;
      pl.roll += (roll - pl.roll) * 0.25;
      if (radius) pl.targetR = radius;
      if (pl.state !== "forming" && pl.state !== "morph") pl.state = "held";
    }

    release(pl, vx, vy) {
      pl.held = false;
      const sp = Math.hypot(vx, vy);
      // hizli savurma firlatir, yavas birakma suzer
      const k = sp > 700 ? 1 : 0.25;
      pl.vx = vx * k; pl.vy = vy * k;
      if (pl.state !== "forming" && pl.state !== "morph") pl.state = "free";
      if (sp > 700) this.onEvent && this.onEvent("throw", pl);
    }

    explode(pl) {
      pl.state = "explode"; pl.stateT = 0;
      for (let i = 0; i < SPHERE_N; i++) {
        const dx = pl.px[i] - pl.x, dy = pl.py[i] - pl.y, d = Math.hypot(dx, dy) || 1;
        const sp = 400 + Math.random() * 900;
        pl.pvx[i] = (dx / d) * sp; pl.pvy[i] = (dy / d) * sp;
      }
      for (let i = 0; i < 70; i++) {
        const a = Math.random() * Math.PI * 2, sp = 300 + Math.random() * 700;
        this.p.emit(pl.x, pl.y, { vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 0.9, size: pl.R * 0.12,
          drag: 2, color: pl.colors[(Math.random() * pl.colors.length) | 0] });
      }
      this.onEvent && this.onEvent("explode", pl);
    }

    morph(pl, kind) {
      pl.state = "morph"; pl.stateT = 0; pl.nextKind = kind;
      for (let i = 0; i < pl.px.length; i++) {
        const a = Math.random() * Math.PI * 2, sp = 120 + Math.random() * 260;
        pl.pvx[i] = Math.cos(a) * sp; pl.pvy[i] = Math.sin(a) * sp;
      }
      this.onEvent && this.onEvent("morph", pl);
    }

    update(dt, W, H) {
      for (const pl of this.planets) {
        pl.stateT += dt;
        pl.spin += dt * (pl.kind === "gunes" ? 0.25 : 0.6);
        pl.R += (pl.targetR - pl.R) * Math.min(1, dt * 8);
        if (pl.state === "forming" && pl.stateT > 0.7) pl.state = pl.held ? "held" : "free";
        if (pl.state === "morph" && pl.stateT > 0.28 && pl.nextKind) {
          pl.setKind(pl.nextKind); pl.nextKind = null;
        }
        if (pl.state === "morph" && pl.stateT > 0.9) pl.state = pl.held ? "held" : "free";
        if (!pl.held && pl.state !== "explode") {
          pl.x += pl.vx * dt; pl.y += pl.vy * dt;
          pl.vx *= Math.max(0, 1 - dt * 0.6); pl.vy *= Math.max(0, 1 - dt * 0.6);
          pl.bob += dt; pl.y += Math.sin(pl.bob * 1.6) * 0.25;
          // ekrandan cikarsa kaybolur
          if (pl.x < -pl.R * 3 || pl.x > W + pl.R * 3 || pl.y < -pl.R * 3 || pl.y > H + pl.R * 3) pl.alpha = 0;
        }
        if (pl.kind === "gunes" && pl.state !== "explode" && Math.random() < 0.7) { // korona
          const a = Math.random() * Math.PI * 2;
          this.p.emit(pl.x + Math.cos(a) * pl.R * 0.95, pl.y + Math.sin(a) * pl.R * 0.95, {
            vx: Math.cos(a) * 40, vy: Math.sin(a) * 40, life: 0.6, size: pl.R * 0.16, grow: -pl.R * 0.1,
            drag: 1, color: Math.random() < 0.5 ? "#ffb23a" : "#ff7a1a" });
        }
        this._points(pl, dt);
        if (pl.state === "explode") pl.alpha = Math.max(0, 1 - pl.stateT / 1.1);
      }
      this.planets = this.planets.filter((pl) => pl.alpha > 0.01);
    }

    _points(pl, dt) {
      const scatter = pl.state === "explode" || (pl.state === "morph" && pl.stateT < 0.28);
      const k = pl.state === "forming" ? 1 - Math.pow(0.02, dt) : 1 - Math.pow(0.0005, dt);
      const total = SPHERE_N + pl.ring.length;
      for (let i = 0; i < total; i++) {
        if (scatter) {
          pl.px[i] += pl.pvx[i] * dt; pl.py[i] += pl.pvy[i] * dt;
          pl.pvx[i] *= 1 - dt * 1.2; pl.pvy[i] *= 1 - dt * 1.2;
          continue;
        }
        let tx, ty;
        if (i < SPHERE_N) [tx, ty] = pl.project(SPHERE[i], i);
        else {
          const rg = pl.ring[i - SPHERE_N];
          const a = rg.a + pl.spin * 0.4;
          [tx, ty] = pl.project([Math.cos(a) * rg.r, 0, Math.sin(a) * rg.r], i);
        }
        pl.px[i] += (tx - pl.px[i]) * k; pl.py[i] += (ty - pl.py[i]) * k;
      }
    }

    draw(ctx, quality) {
      const q = quality || 1;
      const step = q < 0.6 ? 2 : 1;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (const pl of this.planets) {
        const s = pl.R * (pl.kind === "gunes" ? 0.16 : 0.12);
        // arka halka -> kure -> on halka
        const ringBack = [], ringFront = [];
        for (let j = 0; j < pl.ring.length; j++) {
          const rg = pl.ring[j];
          const a = rg.a + pl.spin * 0.4;
          const depth = pl.project([Math.cos(a) * rg.r, 0, Math.sin(a) * rg.r], 0)[2];
          (depth < 0 ? ringBack : ringFront).push(j);
        }
        const drawRing = (list) => {
          for (let n = 0; n < list.length; n += step) {
            const j = list[n], i = SPHERE_N + j;
            ctx.globalAlpha = pl.alpha * 0.55;
            ctx.drawImage(JEL.sprite(pl.ring[j].c), pl.px[i] - s * 0.6, pl.py[i] - s * 0.6, s * 1.2, s * 1.2);
          }
        };
        drawRing(ringBack);
        for (let i = 0; i < SPHERE_N; i += step) {
          const depth = pl.state === "explode" ? 1 : pl.project(SPHERE[i], i)[2];
          const front = depth >= -0.05;
          ctx.globalAlpha = pl.alpha * (front ? 0.55 + depth * 0.45 : 0.08);
          const ss = s * (front ? 1 : 0.7);
          ctx.drawImage(JEL.sprite(pl.colors[i]), pl.px[i] - ss, pl.py[i] - ss, ss * 2, ss * 2);
        }
        drawRing(ringFront);
        if (pl.kind === "gunes" && pl.state !== "explode") {
          const g = ctx.createRadialGradient(pl.x, pl.y, pl.R * 0.4, pl.x, pl.y, pl.R * 1.8);
          g.addColorStop(0, "rgba(255,200,90,0.35)"); g.addColorStop(1, "rgba(255,120,30,0)");
          ctx.globalAlpha = pl.alpha; ctx.fillStyle = g;
          ctx.beginPath(); ctx.arc(pl.x, pl.y, pl.R * 1.8, 0, Math.PI * 2); ctx.fill();
        }
        if (pl.state === "forming" || pl.state === "morph") {
          ctx.globalAlpha = pl.alpha * 0.9;
          ctx.fillStyle = "#ffcf8a";
          ctx.font = "600 12px Rajdhani, 'Segoe UI', sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(NAMES[pl.nextKind || pl.kind], pl.x, pl.y + pl.R * (pl.kind === "saturn" ? 2.5 : 1.5) + 14);
        }
      }
      ctx.restore();
    }

    clear() { this.planets = []; }
  }

  JEL.PlanetSystem = PlanetSystem;
  JEL.PLANETS = KINDS;
  JEL.PLANET_NAMES = NAMES;
})();
