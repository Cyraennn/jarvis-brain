// El Kontrolu: Kitaplik 📚 - rafa uzan, sirti sec, cimdikle tut, kendine cek, kapak, holografik sayfalar.
// Durumlar: idle -> aim (nisangah) -> selected -> grabbed -> flying -> cover -> open -> returning -> idle
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});
  const G = window.CyraenShelfGeom;

  const SELECT_MS = 150;     // ucun hizasindaki sirt bu kadar sabit kalinca secilir
  const AIM_LOST_MS = 450;
  const PULL_FRAC = 0.16;    // ekran genisligine gore cekme mesafesi
  const PULL_GROW = 0.22;    // ya da el boyunun bu oranda buyumesi (kameraya yaklasma)
  const FLY_MS = 750, COVER_MS = 1000, RETURN_MS = 650;

  const DURUM_ADI = { okunacak: "Okunacak", okunuyor: "Okunuyor", bitti: "Bitti" };

  class Bookshelf {
    // app: {api, audio, say(text), T(), source(), demo, key, toast(msg)}
    constructor(app) {
      this.app = app;
      this.books = [];
      this.raf = null;
      this.state = "idle";
      this.stateT = 0;
      this.selId = null;
      this._cand = null; this._candT = 0; this._aimSeen = 0;
      this.tip = null;
      this.out = null;       // {book, rect, img, startPt, startSize, x, y, w, h}
      this.page = 0;
      this.glow = null;      // {id, t}
      this.covers = new Map(); // id -> HTMLImageElement | "yok"
      this.holds = new window.CyraenController.HoldController([
        { jest: "thumbs_up", sure: 1000, ad: "Özet", eylem: { tip: "ozet" } },
        { jest: "fist", sure: 900, ad: "Rafa koy", eylem: { tip: "geri" } },
      ], { cooldownMs: 1200 });
      this._beat = 0;
      this._notebookAsked = new Set();
      this.enabled = true;
    }

    // ------------------------------------------------------------ veri
    setData(snap) {
      this.books = (snap && snap.books) || [];
      this.raf = (snap && snap.raf) || null;
      if (this.out) {
        const fresh = this.books.find((b) => b.id === this.out.book.id);
        if (fresh) this.out.book = fresh;
      }
    }

    shelved() { return this.books.filter((b) => b.kutu && !(this.out && this.out.book.id === b.id && this.state !== "returning")); }

    items() {
      const T = this.app.T();
      return this.books.filter((b) => b.kutu).map((b) => ({ id: b.id, book: b, rect: G.boxToScreen(T, b.kutu) }));
    }

    zoneRect() {
      const T = this.app.T();
      if (this.raf) return G.boxToScreen(T, this.raf);
      const its = this.items();
      return its.length ? G.unionRect(its.map((i) => i.rect), 30) : null;
    }

    inZone(p) {
      const z = this.zoneRect();
      return !!(z && p && G.inRect(z, p, 24));
    }

    hasShelf() { return this.books.some((b) => b.kutu); }

    // kitap disarida mi (diger efektler ve basili tutma kontrolleri kapali)
    busy() { return ["grabbed", "flying", "cover", "open", "returning"].includes(this.state); }

    _set(s, t) { this.state = s; this.stateT = t; }

    // ------------------------------------------------------------ guncelleme
    // hands: [{id, lm, f, pose, events, velocity}] (ekran px)
    update(hands, t, dt, ctx) {
      if (!this.enabled) return;
      const pointer = hands.find((h) => h.pose === "point" && this.inZone(h.f.indexTip));
      const pincher = hands.find((h) => h.pose === "pinch");
      this.tip = pointer ? pointer.f.indexTip : null;

      if (this.state === "idle" || this.state === "aim" || this.state === "selected") {
        if (pointer) {
          this._aimSeen = t;
          if (this.state === "idle") this._set("aim", t);
          const pick = G.pickSpine(this.items(), pointer.f.indexTip, { current: this._cand || this.selId,
            maxDist: Math.max(40, pointer.f.size * 0.6) });
          const id = pick.item ? pick.item.id : null;
          if (id !== this._cand) { this._cand = id; this._candT = t; }
          if (id && id !== this.selId && t - this._candT >= SELECT_MS) {
            this.selId = id; this._set("selected", t);
            this.app.audio.tick();
          }
        } else if (this.state !== "selected" && t - this._aimSeen > AIM_LOST_MS) {
          this._set("idle", t); this._cand = null;
        }
        // secili sirti cimdikle tut
        if (this.state === "selected" && pincher) {
          const it = this.items().find((i) => i.id === this.selId);
          if (it && (G.inRect(it.rect, pincher.f.pinchPt, Math.max(50, pincher.f.size * 0.5)) || this.inZone(pincher.f.pinchPt))) {
            this._grab(it, pincher, t);
          }
        }
        if (this.state === "selected" && !pointer && !pincher && t - this._aimSeen > 2500) {
          this._set("idle", t); this.selId = null; this._cand = null;
        }
        return;
      }

      if (this.state === "grabbed") {
        const o = this.out;
        if (!pincher) { this._set("selected", t); this.out = null; return; } // birakti: yerine
        const W = this.app.T().W;
        const moved = Math.hypot(pincher.f.pinchPt.x - o.startPt.x, pincher.f.pinchPt.y - o.startPt.y);
        const grew = pincher.f.size / o.startSize - 1;
        o.hand = { x: pincher.f.pinchPt.x, y: pincher.f.pinchPt.y };
        if ((moved > W * PULL_FRAC && !this.inZone(pincher.f.pinchPt)) || grew > PULL_GROW || moved > W * PULL_FRAC * 1.8) {
          this._set("flying", t);
          this.app.audio.whoosh();
          this._announce(o.book.id);
        }
        return;
      }

      if (this.state === "flying" && t - this.stateT > FLY_MS) { this._set("cover", t); this.page = 0; }
      if (this.state === "cover") {
        const twoOpen = hands.filter((h) => h.pose === "open").length >= 2;
        if (t - this.stateT > COVER_MS || twoOpen) { this._set("open", t); this.app.audio.page(); this._ensureNotebook(); }
      }
      if (this.state === "open" || this.state === "cover") {
        for (const h of hands) {
          for (const e of h.events || []) {
            if (this.state === "open" && e.type === "swipe_left") this.turn(1);
            if (this.state === "open" && e.type === "swipe_right") this.turn(-1);
            if (e.type === "push") this.putBack(t);
          }
        }
        const r = this.holds.update(hands.map((h) => ({ id: h.id, pose: h.pose, x: h.f.palm.x, y: h.f.palm.y })),
          {}, t);
        this.rings = r.rings;
        for (const f of r.fired) {
          if (f.rule.eylem.tip === "geri") this.putBack(t);
          if (f.rule.eylem.tip === "ozet") this._summary();
        }
        if (t - this._beat > 15000) this._announce(this.out && this.out.book.id);
      }
      if (this.state === "returning" && t - this.stateT > RETURN_MS) {
        this.glow = { id: this.out.book.id, t };
        this.out = null; this.selId = null; this._cand = null;
        this._set("idle", t);
        this.holds.reset();
      }
    }

    _grab(it, hand, t) {
      this.out = { book: it.book, rect: Object.assign({}, it.rect), img: this._crop(it.book.kutu),
        startPt: { x: hand.f.pinchPt.x, y: hand.f.pinchPt.y }, startSize: hand.f.size,
        hand: { x: hand.f.pinchPt.x, y: hand.f.pinchPt.y } };
      this._set("grabbed", t);
      this.app.audio.grab();
    }

    // o anki kareden gercek sirt goruntusu (HAM koordinat, ayna yok -> yazi okunur)
    _crop(box) {
      const src = this.app.source();
      if (!src) return null;
      const vw = src.videoWidth || src.width, vh = src.videoHeight || src.height;
      if (!vw || !vh) return null;
      const c = G.cropRect(box, vw, vh);
      const cv = document.createElement("canvas");
      cv.width = c.sw; cv.height = c.sh;
      try { cv.getContext("2d").drawImage(src, c.sx, c.sy, c.sw, c.sh, 0, 0, c.sw, c.sh); } catch (e) { return null; }
      return cv;
    }

    // Kameraya gosterilen (raf disi) kitap: dogrudan kapak + sayfalar. img: o anki kareden kirpim.
    showBook(book, img) {
      const T = this.app.T();
      const w = Math.min(T.W, T.H) * 0.12;
      this.out = { book, rect: { x: T.W / 2 - w / 2, y: T.H * 0.4, w, h: w * 1.4 }, img,
        startPt: { x: 0, y: 0 }, startSize: 1, hand: { x: 0, y: 0 }, held: true };
      this.page = 0;
      this._set("flying", performance.now());
      this.app.audio.whoosh();
      this._announce(book.id);
    }

    turn(dir) {
      const n = this.spreads().length;
      const next = Math.max(0, Math.min(n - 1, this.page + dir));
      if (next !== this.page) { this.page = next; this.app.audio.page(); }
    }

    putBack(t) {
      if (!this.out || this.state === "returning") return;
      this._set("returning", t || performance.now());
      this.app.audio.whoosh();
      this._announce(null);
    }

    _announce(bookId) {
      this._beat = performance.now();
      if (this.app.demo) return;
      this.app.api("/api/el/durum", { kitap_id: bookId || null, sayfa: this.page }).catch(() => {});
    }

    _summary() {
      const b = this.out && this.out.book;
      if (!b) return;
      this.app.audio.confirm();
      if (this.app.demo) { this.app.toast("Demo: özet okunmaz"); return; }
      if (!b.ad) { this.app.toast("Kitabın adı bilinmiyor. “Cyraen, bu kitabın adı …” deyin."); return; }
      this.app.say(`Bu kitabın özetini oku: ${b.ad}`);
    }

    _ensureNotebook() {
      const b = this.out && this.out.book;
      if (!b || !b.ad || b.defter || this.app.demo || this._notebookAsked.has(b.id)) return;
      this._notebookAsked.add(b.id);
      this.app.api("/api/kitaplik/defter", { id: b.id }).then((r) => {
        if (r && r.id && this.out && this.out.book.id === r.id) this.out.book = r;
      }).catch(() => {});
    }

    cover(b) {
      if (!b || !b.kapak || this.app.demo) return null;
      let c = this.covers.get(b.id + b.kapak);
      if (!c) {
        c = new Image();
        c.src = `/api/kitaplik/kapak/${encodeURIComponent(b.id)}?key=${encodeURIComponent(this.app.key)}&v=${encodeURIComponent(b.kapak)}`;
        this.covers.set(b.id + b.kapak, c);
      }
      return c.complete && c.naturalWidth ? c : null;
    }

    // ------------------------------------------------------------ sayfalar
    pages() {
      const b = this.out ? this.out.book : null;
      if (!b) return [];
      const d = b.defter;
      const cal = b.calibre || {};
      const P = [];
      const kunye = [
        ["", (b.ad || "ADI OKUNAMADI").toLocaleUpperCase("tr-TR"), "title"],
        ["Yazar", b.yazar || "—"],
        ["Durum", DURUM_ADI[b.durum] || "Okunacak"],
      ];
      if (b.sayfa) kunye.push(["Sayfa", String(b.sayfa)]);
      if (cal.seri) kunye.push(["Seri", cal.seri]);
      if (cal.etiketler && cal.etiketler.length) kunye.push(["Etiketler", cal.etiketler.join(", ")]);
      if (cal.formatlar && cal.formatlar.length) kunye.push(["E-kitap", cal.formatlar.join(" · ") + " (Calibre)"]);
      P.push({ title: "KÜNYE", kv: kunye, progress: b.durum === "bitti" ? 1 : b.durum === "okunuyor" ? 0.5 : 0 });
      if (!b.ad) {
        P.push({ title: "CYRAEN", text: "Bu kitabın adı okunamadı. “Cyraen, bu kitabın adı …” deyin; kapak ve sayfalar birkaç saniyede dolar." });
      } else if (!d) {
        P.push({ title: "CYRAEN'İN ÖZETİ", text: "Cyraen sayfaları yazıyor…", pending: true });
      } else if (d.bilinmiyor) {
        P.push({ title: "CYRAEN'İN ÖZETİ", text: "Cyraen bu kitabı tanımıyor. Uydurmamak için sayfa yazmadı; notlarınızı ekleyebilirsiniz." });
      } else {
        P.push({ title: "CYRAEN'İN ÖZETİ", text: d.ozet });
        if (d.ana_fikirler && d.ana_fikirler.length) P.push({ title: "ANA FİKİRLER", list: d.ana_fikirler });
        P.push({ title: "YAZAR VE TEMALAR", text: d.yazar_hakkinda || "", list: d.temalar && d.temalar.length ? d.temalar : null });
        P.push({ title: "NEDEN OKUMALI", text: [d.neden_oku, d.kime_uygun ? "Kime uygun: " + d.kime_uygun : ""].filter(Boolean).join("\n\n") });
        P.push({ title: "RAFINIZDAN BENZERLER", list: d.benzerler && d.benzerler.length ? d.benzerler : ["Rafınızda benzer kitap bulunamadı."] });
      }
      P.push({ title: "NOTLARIM", list: (b.notlar || []).slice(-8).map((n) => n.metin),
        empty: "Henüz not yok. “not al: …” deyin." });
      P.push({ title: "ALINTILARIM", list: (b.alintilar || []).slice(-6).map((a) => `“${a.metin}”` + (a.sayfa ? ` (s.${a.sayfa})` : "")),
        empty: "Alıntı yok. “alıntı ekle: …” deyin." });
      return P;
    }

    spreads() {
      const P = this.pages(), S = [];
      for (let i = 0; i < P.length; i += 2) S.push([P[i], P[i + 1] || null]);
      return S;
    }

    // ------------------------------------------------------------ cizim
    draw(ctx, t) {
      if (!this.enabled) return;
      const T = this.app.T();
      // rafa donen kitabin sirti kisa bir an parlar
      if (this.glow) {
        const b = this.books.find((x) => x.id === this.glow.id);
        const a = 1 - (t - this.glow.t) / 900;
        if (!b || !b.kutu || a <= 0) this.glow = null;
        else glowRect(ctx, G.boxToScreen(T, b.kutu), "#ffcf8a", a);
      }
      // nisangah
      if (this.tip && (this.state === "aim" || this.state === "selected")) crosshair(ctx, this.tip, t);
      // secili sirt
      if (this.selId && (this.state === "aim" || this.state === "selected")) {
        const it = this.items().find((i) => i.id === this.selId);
        if (it) {
          glowRect(ctx, it.rect, "#ffb347", 1);
          label(ctx, it.rect, it.book);
        }
      }
      const o = this.out;
      if (!o) return;
      // raftaki bosluk (eldeki kitabin rafta yeri yok)
      if (this.state !== "grabbed" && !o.held) {
        ctx.save(); ctx.fillStyle = "rgba(0,0,0,0.78)";
        ctx.fillRect(o.rect.x, o.rect.y, o.rect.w, o.rect.h); ctx.restore();
      }
      if (this.state === "grabbed") {
        const j = Math.sin(t / 22) * 2;
        const dx = (o.hand.x - o.startPt.x) * 0.15, dy = (o.hand.y - o.startPt.y) * 0.15;
        drawSpine(ctx, o, o.rect.x + dx + j, o.rect.y + dy, o.rect.w * 1.06, o.rect.h * 1.03, 0);
        glowRect(ctx, { x: o.rect.x + dx + j - 2, y: o.rect.y + dy - 2, w: o.rect.w * 1.06 + 4, h: o.rect.h * 1.03 + 4 }, "#ff8c42", 0.6 + Math.sin(t / 40) * 0.3);
        label(ctx, o.rect, o.book);
        return;
      }
      const card = this._cardRect(T);
      // kitap disaridayken sahne kararir (hologram one ciksin)
      const dimP = this.state === "flying" ? Math.min(1, (t - this.stateT) / FLY_MS)
        : this.state === "returning" ? 1 - Math.min(1, (t - this.stateT) / RETURN_MS) : 1;
      ctx.save(); ctx.fillStyle = `rgba(0,0,0,${0.5 * dimP})`; ctx.fillRect(0, 0, T.W, T.H); ctx.restore();
      if (this.state === "flying" || this.state === "returning") {
        let p = Math.min(1, (t - this.stateT) / (this.state === "flying" ? FLY_MS : RETURN_MS));
        p = easeInOut(p);
        if (this.state === "returning") p = 1 - p;
        const x = lerp(o.rect.x, card.x, p), y = lerp(o.rect.y, card.y, p);
        const w = lerp(o.rect.w, card.w, p), h = lerp(o.rect.h, card.h, p);
        const spin = Math.sin(p * Math.PI) * 0.35;
        if (p < 0.55) drawSpine(ctx, o, x, y, w, h, spin);
        else this._drawCover(ctx, { x, y, w, h }, o.book, spin);
        return;
      }
      if (this.state === "cover") { this._drawCover(ctx, card, o.book, 0); return; }
      if (this.state === "open") this._drawPages(ctx, T, t);
    }

    _cardRect(T) {
      const h = Math.min(T.H * 0.62, 520), w = h * 0.68;
      return { x: T.W / 2 - w / 2, y: T.H * 0.46 - h / 2, w, h };
    }

    _drawCover(ctx, r, b, spin) {
      ctx.save();
      ctx.translate(r.x + r.w / 2, r.y + r.h / 2);
      ctx.scale(Math.cos(spin), 1);
      const x = -r.w / 2, y = -r.h / 2;
      ctx.shadowColor = "#ff8c42"; ctx.shadowBlur = 30;
      const img = this.cover(b);
      if (img) ctx.drawImage(img, x, y, r.w, r.h);
      else {
        const g = ctx.createLinearGradient(x, y, x + r.w, y + r.h);
        g.addColorStop(0, "#2a1608"); g.addColorStop(1, "#0b0705");
        ctx.fillStyle = g; ctx.fillRect(x, y, r.w, r.h);
        ctx.shadowBlur = 0;
        if (this.out && this.out.img) { // kirpilan sirtla sade kapak
          ctx.globalAlpha = 0.9;
          ctx.drawImage(this.out.img, x, y, Math.max(12, r.w * 0.16), r.h);
          ctx.globalAlpha = 1;
        }
        ctx.fillStyle = "#ffcf8a"; ctx.textAlign = "center";
        ctx.font = `700 ${Math.max(14, r.w * 0.085)}px Georgia, serif`;
        wrap(ctx, b.ad || "Adı okunamadı", r.w * 0.68).slice(0, 4).forEach((line, i) =>
          ctx.fillText(line, x + r.w * 0.58, y + r.h * 0.32 + i * r.w * 0.1));
        ctx.font = `500 ${Math.max(11, r.w * 0.05)}px Rajdhani, 'Segoe UI', sans-serif`;
        ctx.fillStyle = "rgba(255,255,255,0.75)";
        ctx.fillText(b.yazar || "", x + r.w * 0.58, y + r.h * 0.78);
      }
      ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255,180,100,0.7)"; ctx.lineWidth = 1.5; ctx.strokeRect(x, y, r.w, r.h);
      ctx.restore();
    }

    _drawPages(ctx, T, t) {
      const spreads = this.spreads();
      if (!spreads.length) return;
      this.page = Math.min(this.page, spreads.length - 1);
      const open = Math.min(1, (t - this.stateT) / 450);
      const W = Math.min(T.W * 0.86, 980), H = Math.min(T.H * 0.66, 560);
      const x = T.W / 2 - W / 2, y = T.H * 0.45 - H / 2;
      ctx.save();
      ctx.globalAlpha = 0.25 + 0.75 * open;
      ctx.translate(T.W / 2, 0); ctx.scale(0.6 + 0.4 * easeOut(open), 1); ctx.translate(-T.W / 2, 0);
      // holografik zemin
      ctx.fillStyle = "rgba(8,12,16,0.9)"; ctx.fillRect(x, y, W, H);
      ctx.strokeStyle = "rgba(255,140,66,0.85)"; ctx.lineWidth = 1.5;
      ctx.shadowColor = "#ff8c42"; ctx.shadowBlur = 16; ctx.strokeRect(x, y, W, H); ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255,140,66,0.35)";
      ctx.beginPath(); ctx.moveTo(x + W / 2, y + 18); ctx.lineTo(x + W / 2, y + H - 18); ctx.stroke();
      ctx.fillStyle = "rgba(255,255,255,0.025)";
      for (let sy = y + ((t / 30) % 4); sy < y + H; sy += 4) ctx.fillRect(x, sy, W, 1);
      const [L, R] = spreads[this.page];
      this._page(ctx, L, x + 28, y + 26, W / 2 - 48, H - 70);
      if (R) this._page(ctx, R, x + W / 2 + 20, y + 26, W / 2 - 48, H - 70);
      // alt bilgi
      ctx.fillStyle = "rgba(255,255,255,0.55)"; ctx.font = "500 13px Rajdhani, 'Segoe UI', sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("✋ savur: sayfa çevir   ·   👍 tut: özet   ·   ✊ tut / ileri it: rafa koy", x + 24, y + H - 18);
      ctx.textAlign = "right";
      ctx.fillText(`${this.page + 1} / ${spreads.length}`, x + W - 24, y + H - 18);
      ctx.restore();
      for (const r of this.rings || []) JEL.drawHoldRing(ctx, r);
    }

    _page(ctx, p, x, y, w, h) {
      if (!p) return;
      ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillStyle = "#ff8c42"; ctx.font = "700 15px Rajdhani, 'Segoe UI', sans-serif";
      ctx.fillText(p.title, x, y);
      ctx.fillStyle = "rgba(255,140,66,0.4)"; ctx.fillRect(x, y + 22, w, 1);
      let cy = y + 36;
      const body = (s, size, color, indent) => {
        const ix = indent || 0;
        ctx.font = `400 ${size || 15}px 'Segoe UI', sans-serif`; ctx.fillStyle = color || "rgba(255,255,255,0.88)";
        for (const para of String(s).split("\n")) {
          for (const line of wrap(ctx, para, w - ix)) {
            if (cy > y + h - 20) return;
            ctx.fillText(line, x + ix, cy); cy += (size || 15) * 1.45;
          }
          cy += 4;
        }
      };
      if (p.kv) {
        for (const [k, v, kind] of p.kv) {
          if (kind === "title") {
            ctx.font = "700 22px Georgia, serif"; ctx.fillStyle = "#ffe2bf";
            for (const line of wrap(ctx, v, w).slice(0, 3)) { ctx.fillText(line, x, cy); cy += 28; }
            cy += 8; continue;
          }
          ctx.font = "600 12px Rajdhani, 'Segoe UI', sans-serif"; ctx.fillStyle = "rgba(255,180,110,0.8)";
          ctx.fillText(k.toLocaleUpperCase("tr-TR"), x, cy); cy += 16;
          body(v, 15);
        }
        if (p.progress !== undefined) {
          ctx.fillStyle = "rgba(255,255,255,0.12)"; ctx.fillRect(x, cy + 6, w, 6);
          ctx.fillStyle = "#ff8c42"; ctx.fillRect(x, cy + 6, w * p.progress, 6);
        }
        return;
      }
      if (p.text) body(p.text, 15, p.pending ? "rgba(255,200,140,0.8)" : undefined);
      const list = p.list && p.list.length ? p.list : p.empty ? [p.empty] : [];
      for (const item of list) {
        if (cy > y + h - 20) break;
        ctx.fillStyle = "#ff8c42"; ctx.fillText("▸", x, cy);
        body(item, 14, undefined, 16);
      }
    }
  }

  // ------------------------------------------------------------ cizim yardimcilari
  function lerp(a, b, t) { return a + (b - a) * t; }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function easeInOut(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

  function wrap(ctx, text, maxW) {
    const words = String(text || "").split(/\s+/), lines = [];
    let line = "";
    for (const w of words) {
      const test = line ? line + " " + w : w;
      if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = w; } else line = test;
    }
    if (line) lines.push(line);
    return lines;
  }

  function glowRect(ctx, r, color, a) {
    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, a));
    ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.shadowColor = color; ctx.shadowBlur = 16;
    ctx.strokeRect(r.x - 1, r.y - 1, r.w + 2, r.h + 2);
    ctx.restore();
  }

  function label(ctx, r, b) {
    const text = b.ad ? (b.ad + (b.yazar ? " · " + b.yazar.split(/\s+/).slice(-1)[0] : "")).toLocaleUpperCase("tr-TR")
      : "ADI OKUNAMADI · K İLE ADLANDIRIN";
    ctx.save();
    ctx.font = "700 14px Rajdhani, 'Segoe UI', sans-serif";
    const w = ctx.measureText(text).width + 18;
    let x = r.x + r.w / 2 - w / 2;
    x = Math.max(8, Math.min(ctx.canvas.width - w - 8, x));
    const y = Math.max(8, r.y - 34);
    ctx.fillStyle = "rgba(0,0,0,0.72)"; ctx.fillRect(x, y, w, 24);
    ctx.strokeStyle = "#ffb347"; ctx.lineWidth = 1; ctx.strokeRect(x, y, w, 24);
    ctx.fillStyle = "#ffcf8a"; ctx.textBaseline = "middle"; ctx.fillText(text, x + 9, y + 12);
    ctx.restore();
  }

  function crosshair(ctx, p, t) {
    ctx.save();
    ctx.strokeStyle = "#ffcf8a"; ctx.lineWidth = 1.5; ctx.shadowColor = "#ff8c42"; ctx.shadowBlur = 8;
    const r = 9 + Math.sin(t / 160) * 1.5;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(p.x - r - 6, p.y); ctx.lineTo(p.x - r + 3, p.y); ctx.moveTo(p.x + r - 3, p.y); ctx.lineTo(p.x + r + 6, p.y);
    ctx.moveTo(p.x, p.y - r - 6); ctx.lineTo(p.x, p.y - r + 3); ctx.moveTo(p.x, p.y + r - 3); ctx.lineTo(p.x, p.y + r + 6);
    ctx.stroke();
    ctx.restore();
  }

  function drawSpine(ctx, o, x, y, w, h, spin) {
    ctx.save();
    ctx.translate(x + w / 2, y + h / 2); ctx.rotate(spin);
    ctx.shadowColor = "#ff8c42"; ctx.shadowBlur = 18;
    if (o.img) ctx.drawImage(o.img, -w / 2, -h / 2, w, h);
    else { ctx.fillStyle = "#5a3a22"; ctx.fillRect(-w / 2, -h / 2, w, h); }
    ctx.restore();
  }

  // basili tutma halkasi (el-app ve kitaplik ortak)
  JEL.drawHoldRing = function (ctx, r) {
    ctx.save();
    const R = 34;
    ctx.lineWidth = 5; ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.beginPath(); ctx.arc(r.x, r.y - 90, R, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = "#ff8c42"; ctx.shadowColor = "#ff8c42"; ctx.shadowBlur = 14;
    ctx.beginPath(); ctx.arc(r.x, r.y - 90, R, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * r.progress); ctx.stroke();
    ctx.shadowBlur = 0; ctx.fillStyle = "#ffcf8a"; ctx.font = "700 12px Rajdhani, 'Segoe UI', sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText((r.rule.ad || "").toLocaleUpperCase("tr-TR"), r.x, r.y - 90);
    ctx.restore();
  };

  JEL.Bookshelf = Bookshelf;
  JEL.wrapText = wrap;
})();
