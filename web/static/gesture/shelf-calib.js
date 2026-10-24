// El Kontrolu: kitaplik ayari (K tusu). Kitapligi tara, belirsiz (amber kesikli) kutulara tiklayip
// adini yaz, bos yere surukleyerek kutu ciz, kutuyu tasi, kosesinden boyutlandir, Del ile sil, Kaydet.
// Adsiz kutuya yazarken kayitli (rafta yeri olmayan) kitaplar oneri olarak cikar; secince o kitap
// bu kutuya yerlesir (notlari ve ozeti korunur).
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});
  const G = window.JarvisShelfGeom;
  const HANDLE = 10;

  class ShelfCalib {
    // app: {api, apiRaw, T(), source(), canvas, demo, toast, audio, drift, bookshelf, onSaved}
    constructor(app, panel) {
      this.app = app;
      this.panel = panel;
      this.active = false;
      this.items = [];      // [{id?, ad, yazar, kutu (ham), link?, dirty}]
      this.deleted = [];
      this.sel = -1;
      this.drag = null;
      this.scan = null;     // {job, tiles: [], found: [], text, t}
      this._buildPanel();
      this._bindMouse();
    }

    _buildPanel() {
      const p = this.panel;
      p.innerHTML = "";
      const h = document.createElement("h3"); h.textContent = "KİTAPLIK AYARI"; p.appendChild(h);
      const row = document.createElement("div"); row.className = "calrow";
      const btn = (label, fn, cls) => {
        const b = document.createElement("button"); b.textContent = label; if (cls) b.className = cls;
        b.addEventListener("click", fn); row.appendChild(b); return b;
      };
      this.btnScan = btn("Kitaplığı tara", () => this.startScan(false), "primary");
      btn("Tam kare", () => this.startScan(true));
      btn("Kaydet", () => this.save(), "primary");
      btn("Çık (K)", () => this.toggle(false));
      p.appendChild(row);
      this.status = document.createElement("div"); this.status.className = "calstatus"; p.appendChild(this.status);
      const help = document.createElement("p"); help.className = "fxhint";
      help.textContent = "Amber kesikli = belirsiz. Tıkla → adını yaz (Enter). Boş yere sürükle → yeni kutu. Kutuyu sürükle → taşı, köşeden boyutlandır, Del → sil.";
      p.appendChild(help);
      // ad giris kutusu (secili kutunun ustunde)
      this.input = document.createElement("input");
      this.input.className = "calinput"; this.input.placeholder = "Kitap adı (Enter)";
      this.input.setAttribute("list", "calSuggest");
      this.input.style.display = "none";
      this.datalist = document.createElement("datalist"); this.datalist.id = "calSuggest";
      document.body.appendChild(this.input); document.body.appendChild(this.datalist);
      this.input.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Enter") { this._applyName(this.input.value); this.input.blur(); }
        if (e.key === "Escape") { this.input.style.display = "none"; this.input.blur(); }
      });
    }

    toggle(on) {
      this.active = on === undefined ? !this.active : on;
      this.panel.style.display = this.active ? "block" : "none";
      this.input.style.display = "none";
      if (this.active) this.load();
      this.app.canvas.style.pointerEvents = this.active ? "auto" : "none";
    }

    load() {
      const books = this.app.bookshelf.books;
      this.items = books.filter((b) => b.kutu).map((b) => ({ id: b.id, ad: b.ad, yazar: b.yazar, kutu: Object.assign({}, b.kutu), dirty: false }));
      this.deleted = []; this.sel = -1;
      // oneriler: rafta yeri olmayan adli kitaplar
      this.datalist.innerHTML = "";
      for (const b of books.filter((x) => !x.kutu && x.ad)) {
        const o = document.createElement("option"); o.value = b.ad; o.label = b.yazar || ""; this.datalist.appendChild(o);
      }
      const named = this.items.filter((i) => i.ad).length;
      this._status(`${this.items.length} kutu · ${named} adlı · ${this.items.length - named} belirsiz`);
    }

    _status(s) { this.status.textContent = s; }

    // ------------------------------------------------------------ tarama
    async startScan(full) {
      if (this.scan && this.scan.running) return;
      const src = this.app.source();
      if (!src) { this.app.toast("Kamera hazır değil"); return; }
      if (this.app.demo) { this._demoScan(); return; }
      this._status("Kare alınıyor…");
      let blob;
      try { blob = await this._grabFrame(); } catch (e) { this._status("Kare alınamadı: " + e); return; }
      this.scan = { running: true, tiles: [], found: [], t: performance.now(), text: "Taranıyor…" };
      this.app.audio.scan();
      const q = full ? "?tam=1" : "";
      try {
        const r = await this.app.apiRaw("/api/kitaplik/tara" + q, blob);
        if (r.error) throw new Error(r.error);
        this.scan.job = r.job;
        this._status("Tarama sürüyor (20-30 sn)…");
      } catch (e) {
        this.scan.running = false;
        this._status("Tarama başlatılamadı: " + e.message);
      }
    }

    // tam cozunurlukte tek kare (takip 640x480'de kalir)
    async _grabFrame() {
      const src = this.app.source();
      const track = src.srcObject && src.srcObject.getVideoTracks ? src.srcObject.getVideoTracks()[0] : null;
      if (track && typeof ImageCapture !== "undefined") {
        try {
          const ic = new ImageCapture(track);
          const bmp = await ic.grabFrame();
          return await toJpeg(bmp, bmp.width, bmp.height);
        } catch (e) { /* asagidaki yola dus */ }
      }
      const vw = src.videoWidth || src.width, vh = src.videoHeight || src.height;
      return toJpeg(src, vw, vh);
    }

    // SSE kitaplik.tarama olaylari
    onScanEvent(e) {
      if (!this.scan || (this.scan.job && e.job !== this.scan.job)) {
        if (!this.scan && e.faz === "basladi") this.scan = { running: true, tiles: [], found: [], t: performance.now(), job: e.job };
        else if (!this.scan) return;
      }
      const s = this.scan;
      if (e.faz === "parca" && e.tile) s.tiles.push({ tile: e.tile, t: performance.now() });
      if (e.faz === "bulundu") {
        for (const k of e.kutular || []) s.found.push(Object.assign({ t: performance.now() + s.found.length * 25 }, k));
        this._status(`Taranıyor… ${e.bitti}/${e.toplam} parça · ${s.found.length} sırt`);
      }
      if (e.faz === "bitti") {
        s.running = false; s.doneT = performance.now();
        s.text = `${e.taninan} kitap tanındı · ${e.belirsiz} belirsiz`;
        this._status(s.text + (e.hatalar && e.hatalar.length ? ` (${e.hatalar.length} parça okunamadı)` : ""));
        this.app.audio.confirm();
        this.app.toast(s.text);
        this._saveReference();
        this.app.reload().then(() => { if (this.active) this.load(); });
      }
      if (e.faz === "hata") {
        s.running = false; s.doneT = performance.now(); s.text = "Tarama başarısız";
        this._status("Tarama başarısız: " + e.hata);
        this.app.toast("Tarama başarısız: " + e.hata);
      }
    }

    _demoScan() {
      const truth = this.app.demoTruth();
      this.scan = { running: true, tiles: [], found: [], t: performance.now(), demo: true };
      truth.boxes.forEach((b, i) => this.scan.found.push({ kutu: b.kutu, ad: b.ad, t: performance.now() + 400 + i * 40 }));
      setTimeout(() => {
        this.scan.running = false; this.scan.doneT = performance.now();
        this.scan.text = `${truth.boxes.length} kitap tanındı · 0 belirsiz (demo)`;
        this.app.toast(this.scan.text);
      }, 400 + truth.boxes.length * 40);
    }

    _saveReference() {
      if (this.app.demo) return;
      try {
        const gri = window.JarvisShelfDrift.thumb(this.app.source());
        const ref = { w: 32, h: 24, gri };
        this.app.drift.setReference(ref);
        this.app.api("/api/kitaplik/kaydet", { items: [], silinen: [], referans: ref }).catch(() => {});
      } catch (e) { /* yoksay */ }
    }

    // ------------------------------------------------------------ duzenleme
    _bindMouse() {
      const cv = this.app.canvas;
      cv.addEventListener("mousedown", (e) => this._down(e));
      window.addEventListener("mousemove", (e) => this._move(e));
      window.addEventListener("mouseup", () => this._up());
      window.addEventListener("keydown", (e) => {
        if (!this.active || document.activeElement === this.input) return;
        if ((e.key === "Delete" || e.key === "Backspace") && this.sel >= 0) { this._delete(this.sel); e.preventDefault(); }
      });
    }

    _rects() { const T = this.app.T(); return this.items.map((it) => G.boxToScreen(T, it.kutu)); }

    _down(e) {
      if (!this.active) return;
      const p = { x: e.clientX, y: e.clientY };
      const rects = this._rects();
      // once secili kutunun koseleri
      if (this.sel >= 0) {
        const r = rects[this.sel];
        const corners = [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]];
        const ci = corners.findIndex(([cx, cy]) => Math.abs(p.x - cx) < HANDLE && Math.abs(p.y - cy) < HANDLE);
        if (ci >= 0) { this.drag = { kind: "resize", corner: ci, r: Object.assign({}, r) }; return; }
      }
      for (let i = rects.length - 1; i >= 0; i--) {
        if (G.inRect(rects[i], p, 2)) {
          this.sel = i;
          this.drag = { kind: "move", start: p, r: Object.assign({}, rects[i]), moved: false };
          return;
        }
      }
      this.sel = -1; this.input.style.display = "none";
      this.drag = { kind: "new", start: p, r: { x: p.x, y: p.y, w: 0, h: 0 } };
    }

    _move(e) {
      if (!this.drag) return;
      const p = { x: e.clientX, y: e.clientY }, d = this.drag, T = this.app.T();
      if (d.kind === "new") { d.r = { x: d.start.x, y: d.start.y, w: p.x - d.start.x, h: p.y - d.start.y }; return; }
      const it = this.items[this.sel];
      if (!it) return;
      let r;
      if (d.kind === "move") {
        if (Math.hypot(p.x - d.start.x, p.y - d.start.y) > 3) d.moved = true;
        r = { x: d.r.x + p.x - d.start.x, y: d.r.y + p.y - d.start.y, w: d.r.w, h: d.r.h };
      } else {
        const x0 = d.corner % 2 === 0 ? p.x : d.r.x, x1 = d.corner % 2 === 1 ? p.x : d.r.x + d.r.w;
        const y0 = d.corner < 2 ? p.y : d.r.y, y1 = d.corner >= 2 ? p.y : d.r.y + d.r.h;
        r = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
      }
      const box = G.screenRectToBox(T, r);
      if (box) { it.kutu = box; it.dirty = true; }
    }

    _up() {
      const d = this.drag;
      this.drag = null;
      if (!d) return;
      if (d.kind === "new" && Math.abs(d.r.w) > 8 && Math.abs(d.r.h) > 8) {
        const box = G.screenRectToBox(this.app.T(), d.r);
        if (box) { this.items.push({ ad: null, yazar: null, kutu: box, dirty: true }); this.sel = this.items.length - 1; this._askName(); }
      } else if (d.kind === "move" && !d.moved) this._askName();
    }

    _askName() {
      const it = this.items[this.sel];
      if (!it) return;
      const r = this._rects()[this.sel];
      this.input.value = it.ad || "";
      this.input.style.display = "block";
      this.input.style.left = Math.max(8, Math.min(innerWidth - 300, r.x + r.w / 2 - 140)) + "px";
      this.input.style.top = Math.max(8, r.y - 44) + "px";
      setTimeout(() => this.input.focus(), 0);
    }

    _applyName(v) {
      const it = this.items[this.sel];
      this.input.style.display = "none";
      if (!it) return;
      const name = (v || "").trim();
      const reg = this.app.bookshelf.books.find((b) => !b.kutu && b.ad && b.ad.toLocaleLowerCase("tr-TR") === name.toLocaleLowerCase("tr-TR"));
      if (reg) { it.link = reg.id; it.ad = reg.ad; it.yazar = reg.yazar; } else { it.ad = name || null; delete it.link; }
      it.dirty = true;
    }

    _delete(i) {
      const it = this.items[i];
      if (it && it.id) this.deleted.push(it.id);
      this.items.splice(i, 1); this.sel = -1; this.input.style.display = "none";
    }

    async save() {
      if (this.app.demo) { this.app.toast("Demo: değişiklikler kaydedilmez"); return; }
      const items = this.items.filter((i) => i.dirty).map((i) => {
        const o = { kutu: i.kutu };
        if (i.id) o.id = i.id;
        if (i.link) o.link = i.link;
        o.ad = i.ad || null;
        return o;
      });
      try {
        await this.app.api("/api/kitaplik/kaydet", { items, silinen: this.deleted });
        this.app.toast("Kitaplık kaydedildi");
        this.app.audio.confirm();
        await this.app.reload();
        this.load();
      } catch (e) { this.app.toast("Kaydedilemedi: " + e); }
    }

    // ------------------------------------------------------------ cizim
    draw(ctx, t) {
      const T = this.app.T();
      const s = this.scan;
      if (s) this._drawScan(ctx, T, t);
      if (!this.active) return;
      const rects = this._rects();
      ctx.save();
      rects.forEach((r, i) => {
        const it = this.items[i];
        ctx.lineWidth = i === this.sel ? 2.5 : 1.4;
        if (it.ad) { ctx.setLineDash([]); ctx.strokeStyle = "rgba(52,227,240,0.85)"; }
        else { ctx.setLineDash([5, 4]); ctx.strokeStyle = "rgba(255,179,71,0.95)"; }
        ctx.strokeRect(r.x, r.y, r.w, r.h);
        if (i === this.sel) {
          ctx.setLineDash([]); ctx.fillStyle = "#ffcf8a";
          for (const [cx, cy] of [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]]) ctx.fillRect(cx - 4, cy - 4, 8, 8);
          if (it.ad) {
            ctx.font = "600 12px Rajdhani, 'Segoe UI', sans-serif"; ctx.fillStyle = "#e6fbff";
            ctx.fillText(it.ad, r.x, r.y + r.h + 14);
          }
        }
      });
      if (this.drag && this.drag.kind === "new") {
        const r = this.drag.r;
        ctx.setLineDash([4, 3]); ctx.strokeStyle = "#ffcf8a"; ctx.strokeRect(r.x, r.y, r.w, r.h);
      }
      ctx.restore();
    }

    _drawScan(ctx, T, t) {
      const s = this.scan;
      const now = performance.now();
      if (!s.running && now - (s.doneT || now) > 4000) { this.scan = null; return; }
      ctx.save();
      // tarama cizgisi raf boyunca gezer
      const z = this.app.bookshelf.zoneRect() || { x: 0, y: 0, w: T.W, h: T.H };
      if (s.running) {
        const px = z.x + z.w * (((now - s.t) / 2200) % 1);
        const g = ctx.createLinearGradient(px - 60, 0, px, 0);
        g.addColorStop(0, "rgba(255,140,66,0)"); g.addColorStop(1, "rgba(255,140,66,0.45)");
        ctx.fillStyle = g; ctx.fillRect(px - 60, z.y, 60, z.h);
        ctx.fillStyle = "#ffcf8a"; ctx.fillRect(px, z.y, 2, z.h);
        for (const tl of s.tiles.slice(-6)) {
          const r = G.boxToScreen(T, tl.tile);
          ctx.strokeStyle = "rgba(255,140,66,0.25)"; ctx.setLineDash([3, 6]); ctx.strokeRect(r.x, r.y, r.w, r.h);
        }
        ctx.setLineDash([]);
      }
      // bulunan sirtlar sirayla parlar
      for (const f of s.found) {
        const age = now - f.t;
        if (age < 0) continue;
        const r = G.boxToScreen(T, f.kutu);
        const a = Math.max(0.25, 1 - age / 1500);
        ctx.globalAlpha = a;
        ctx.strokeStyle = f.ad ? "#34e3f0" : "#ffb347"; ctx.lineWidth = 2; ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = 10;
        ctx.strokeRect(r.x, r.y, r.w, r.h);
      }
      ctx.globalAlpha = 1; ctx.shadowBlur = 0;
      if (s.text && !s.running) {
        ctx.font = "700 20px Rajdhani, 'Segoe UI', sans-serif"; ctx.textAlign = "center";
        const w = ctx.measureText(s.text).width + 40;
        ctx.fillStyle = "rgba(0,0,0,0.7)"; ctx.fillRect(T.W / 2 - w / 2, T.H - 150, w, 40);
        ctx.fillStyle = "#ffcf8a"; ctx.fillText(s.text, T.W / 2, T.H - 123);
      }
      ctx.restore();
    }
  }

  async function toJpeg(src, w, h) {
    const cv = document.createElement("canvas");
    cv.width = w; cv.height = h;
    cv.getContext("2d").drawImage(src, 0, 0, w, h);
    return new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("jpeg"))), "image/jpeg", 0.92));
  }

  JEL.ShelfCalib = ShelfCalib;
  JEL.toJpeg = toJpeg;
})();
