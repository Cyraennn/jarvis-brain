// El Kontrolu: kare zamanlayicisi. Algilama yalnizca YENI kamera karesinde calisir
// (requestVideoFrameCallback); el ~30 Hz, yuz ~5 Hz, ikisi ayni karede calismaz.
// Cizim ayri bir requestAnimationFrame dongusunde (ekran yenileme hizinda) yapilir.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});

  class FrameScheduler {
    // source: <video> ya da <canvas> (demo); tasks: [{name, hz, run(source, tMs)}]
    constructor(source, tasks) {
      this.source = source;
      this.tasks = tasks.map((t) => Object.assign({ last: -1e9, ms: 0 }, t));
      this.running = false;
      this._lastTs = 0;
      this._handle = null;
    }

    start() {
      if (this.running) return;
      this.running = true;
      this._loop();
    }

    stop() { this.running = false; }

    _schedule() {
      const v = this.source;
      if (v && typeof v.requestVideoFrameCallback === "function") v.requestVideoFrameCallback(() => this._loop());
      else requestAnimationFrame(() => this._loop());
    }

    _loop() {
      if (!this.running) return;
      // MediaPipe VIDEO modu kesin artan zaman damgasi ister
      let now = performance.now();
      if (now <= this._lastTs) now = this._lastTs + 1;
      this._lastTs = now;
      // vadesi en cok gecmis gorev (ayni karede tek algilama)
      let pick = null, lateness = 0;
      for (const t of this.tasks) {
        if (t.enabled === false) continue;
        const due = now - t.last - 1000 / t.hz;
        if (due >= -4 && due + 1000 / t.hz > lateness) { pick = t; lateness = due + 1000 / t.hz; }
      }
      if (pick) {
        const t0 = performance.now();
        try { pick.run(this.source, now); } catch (e) { console.warn("[el] algilama hatasi", pick.name, e); }
        pick.ms = pick.ms * 0.8 + (performance.now() - t0) * 0.2;
        pick.last = now;
      }
      this._schedule();
    }

    task(name) { return this.tasks.find((t) => t.name === name); }
  }

  JEL.FrameScheduler = FrameScheduler;
})();
