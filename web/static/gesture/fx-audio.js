// El Kontrolu: efekt sesleri anlik sentezlenir (WebAudio; ses dosyasi yok). M tusu susturur.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});

  class FxAudio {
    constructor() {
      this.ctx = null; this.master = null; this.muted = false; this._fire = null; this._noise = null;
    }

    // Tarayici, kullanici etkilesimi olmadan sesi baslatmaz: ilk tik/tusta cagrilir.
    unlock() {
      if (this.ctx) { if (this.ctx.state === "suspended") this.ctx.resume(); return; }
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.muted ? 0 : 0.5;
      this.master.connect(this.ctx.destination);
      const len = this.ctx.sampleRate * 2;
      this._noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const d = this._noise.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    }

    setMuted(m) {
      this.muted = !!m;
      if (this.master) this.master.gain.setTargetAtTime(this.muted ? 0 : 0.5, this.ctx.currentTime, 0.05);
    }

    _ok() { return this.ctx && !this.muted && this.ctx.state === "running"; }

    _tone(freq, dur, type, gain, slideTo) {
      if (!this._ok()) return;
      const t = this.ctx.currentTime, o = this.ctx.createOscillator(), g = this.ctx.createGain();
      o.type = type || "sine"; o.frequency.setValueAtTime(freq, t);
      if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain || 0.3, t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g).connect(this.master); o.start(t); o.stop(t + dur + 0.05);
    }

    _noiseBurst(dur, freq, q, gain, sweepTo) {
      if (!this._ok()) return;
      const t = this.ctx.currentTime, src = this.ctx.createBufferSource(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
      src.buffer = this._noise; f.type = "bandpass"; f.frequency.setValueAtTime(freq, t); f.Q.value = q || 1;
      if (sweepTo) f.frequency.exponentialRampToValueAtTime(sweepTo, t + dur);
      g.gain.setValueAtTime(gain || 0.4, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      src.connect(f).connect(g).connect(this.master); src.start(t, Math.random()); src.stop(t + dur + 0.05);
    }

    // ates: surekli hafif citirti; yogunluk 0-1
    fire(level) {
      if (!this.ctx) return;
      if (!this._fire && level > 0.05 && this._ok()) {
        const src = this.ctx.createBufferSource(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
        src.buffer = this._noise; src.loop = true; f.type = "lowpass"; f.frequency.value = 900; g.gain.value = 0;
        src.connect(f).connect(g).connect(this.master); src.start();
        this._fire = { src, g };
      }
      if (this._fire) {
        this._fire.g.gain.setTargetAtTime(this.muted ? 0 : level * 0.12, this.ctx.currentTime, 0.1);
        if (level > 0.3 && Math.random() < 0.15) this._noiseBurst(0.04, 2500 + Math.random() * 2000, 4, 0.12 * level);
      }
    }

    whoosh() { this._noiseBurst(0.5, 300, 0.8, 0.35, 2400); }
    boom() { this._tone(90, 0.7, "sine", 0.6, 32); this._noiseBurst(0.6, 600, 0.7, 0.5, 80); }
    zap() { this._noiseBurst(0.07, 3500, 2, 0.25); this._tone(1200 + Math.random() * 800, 0.06, "sawtooth", 0.06, 300); }
    chime() { this._tone(660, 0.5, "sine", 0.18); setTimeout(() => this._tone(990, 0.6, "sine", 0.12), 90); }
    lock() { this._tone(1320, 0.08, "square", 0.08); setTimeout(() => this._tone(1760, 0.16, "square", 0.08), 90); }
    tick() { this._tone(2200, 0.03, "sine", 0.05); }
    grab() { this._tone(520, 0.12, "triangle", 0.15, 780); }
    page() { this._noiseBurst(0.22, 1800, 0.6, 0.18, 600); }
    confirm() { this._tone(880, 0.12, "sine", 0.2); setTimeout(() => this._tone(1320, 0.2, "sine", 0.18), 110); }
    scan() { this._tone(300, 1.2, "sawtooth", 0.04, 1200); }
  }

  JEL.FxAudio = FxAudio;
})();
