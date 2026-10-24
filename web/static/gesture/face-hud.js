// El Kontrolu: yuz HUD kilidi (F tusu). YALNIZCA YUZ ALGILAMA (MediaPipe BlazeFace):
// kim oldugunuzu bilmez, biyometrik veri tutmaz, goruntu hicbir yere gitmez ve hicbir
// yetkiyi acip kapatmaz; "TANINDI · YETKI: TAM" yazisi gosteri metnidir.
// Etiket yalnizca kameraya en yakin (en buyuk) yuze verilir; digerleri "KISI · TANIMLANMADI".
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});

  const LOCK_MS = 1100;   // kilitlenme animasyonu
  const LOST_MS = 1500;   // yuz bu kadar gorunmezse kilit duser

  class FaceHud {
    constructor(name) {
      this.name = (name || "KULLANICI").toLocaleUpperCase("tr-TR");
      this.faces = [];          // [{rect (ekran px), score}]
      this.main = null;         // yumusatilmis ana yuz
      this.state = "none";      // none | locking | locked
      this.stateT = 0;
      this.lastSeen = 0;
      this.onLocked = null;     // () => void (karsilama sesi)
    }

    // dets: [{rect: {x,y,w,h} ekran px, score}]
    feed(dets, t) {
      this.faces = dets.slice().sort((a, b) => b.rect.w * b.rect.h - a.rect.w * a.rect.h);
      const top = this.faces[0];
      if (!top) return;
      this.lastSeen = t;
      if (!this.main) this.main = Object.assign({}, top.rect, { score: top.score });
      else {
        const k = 0.4;
        for (const key of ["x", "y", "w", "h"]) this.main[key] += (top.rect[key] - this.main[key]) * k;
        this.main.score = top.score;
      }
      if (this.state === "none") { this.state = "locking"; this.stateT = t; }
    }

    update(t) {
      if (this.state !== "none" && t - this.lastSeen > LOST_MS) {
        this.state = "none"; this.main = null; this.faces = [];
      }
      if (this.state === "locking" && t - this.stateT > LOCK_MS) {
        this.state = "locked"; this.stateT = t;
        this.onLocked && this.onLocked();
      }
    }

    draw(ctx, t) {
      if (!this.main || this.state === "none") return;
      const m = this.main;
      const locking = this.state === "locking";
      const p = locking ? Math.min(1, (t - this.stateT) / LOCK_MS) : 1;
      const color = locking ? "#ffb347" : "#ff8c42";
      // kose parantezleri: buyukten kapanarak yuze oturur
      const pad = (1 - easeOut(p)) * m.w * 0.6 + m.w * 0.08;
      const x0 = m.x - pad, y0 = m.y - pad, x1 = m.x + m.w + pad, y1 = m.y + m.h + pad;
      const L = Math.min(m.w, m.h) * 0.22;
      ctx.save();
      ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.shadowColor = color; ctx.shadowBlur = 12;
      corner(ctx, x0, y0, L, 1, 1); corner(ctx, x1, y0, L, -1, 1);
      corner(ctx, x0, y1, L, 1, -1); corner(ctx, x1, y1, L, -1, -1);
      // tarama cizgisi (kilitlenirken)
      if (locking) {
        const sy = y0 + (y1 - y0) * ((t / 700) % 1);
        ctx.globalAlpha = 0.5; ctx.beginPath(); ctx.moveTo(x0, sy); ctx.lineTo(x1, sy); ctx.stroke();
        ctx.globalAlpha = 1;
      } else {
        // ince nisangah
        ctx.lineWidth = 1; ctx.globalAlpha = 0.45;
        ctx.beginPath(); ctx.arc(m.x + m.w / 2, m.y + m.h / 2, m.w * 0.62, (t / 900) % (Math.PI * 2), (t / 900) % (Math.PI * 2) + 1.2); ctx.stroke();
        ctx.globalAlpha = 1;
      }
      ctx.shadowBlur = 0;
      ctx.font = "700 15px Rajdhani, 'Segoe UI', sans-serif";
      ctx.textAlign = "left"; ctx.textBaseline = "top";
      const label = locking ? "KİLİTLENİYOR…" : `${this.name} · TANINDI · YETKİ: TAM`;
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(0,0,0,0.55)"; ctx.fillRect(x0, y1 + 8, tw + 16, 24);
      ctx.fillStyle = color; ctx.fillText(label, x0 + 8, y1 + 12);
      ctx.font = "500 12px Rajdhani, 'Segoe UI', sans-serif";
      ctx.fillStyle = "rgba(255,255,255,0.7)";
      ctx.fillText(`ALGILAMA GÜVENİ ${(m.score * 100).toFixed(0)}% · yalnızca yüz algılama`, x0 + 2, y1 + 36);
      // diger yuzler
      for (const f of this.faces.slice(1)) {
        const r = f.rect;
        ctx.strokeStyle = "rgba(255,255,255,0.45)"; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
        ctx.strokeRect(r.x, r.y, r.w, r.h); ctx.setLineDash([]);
        ctx.fillStyle = "rgba(0,0,0,0.5)"; ctx.fillRect(r.x, r.y + r.h + 4, 168, 20);
        ctx.fillStyle = "rgba(255,255,255,0.8)"; ctx.font = "600 12px Rajdhani, 'Segoe UI', sans-serif";
        ctx.fillText("KİŞİ · TANIMLANMADI", r.x + 6, r.y + r.h + 8);
      }
      ctx.restore();
    }

    reset() { this.state = "none"; this.main = null; this.faces = []; }
  }

  function corner(ctx, x, y, L, sx, sy) {
    ctx.beginPath(); ctx.moveTo(x, y + L * sy); ctx.lineTo(x, y); ctx.lineTo(x + L * sx, y); ctx.stroke();
  }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

  JEL.FaceHud = FaceHud;
})();
