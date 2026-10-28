// El Kontrolu: efektleri ac/kapat (⚙ efektler / E tusu). Secim bu cihazda saklanir.
// Kapali efekt hic tetiklenmez.
(function () {
  "use strict";
  const JEL = (window.JEL = window.JEL || {});
  const KEY = "jv_el_fx_v1";

  const ITEMS = [
    ["ates", "Ateş (açık el)"], ["muhur", "Mühür halkaları (iki açık el)"], ["gezegen", "Gezegen (çimdik)"],
    ["patlatma", "Patlatma (yumruk → açık el)"], ["simsek", "Şimşek (iki işaret)"], ["iz", "Işık izi (tek işaret)"],
    ["kontroller", "Jarvis kontrolleri (👍 ✌️ ✊)"], ["yuz", "Yüz kilidi"], ["kitaplik", "Kitaplık"],
    ["sesler", "Efekt sesleri"], ["rafAtesYok", "Raf bölgesinde ateş/iz yok"],
  ];
  const DEFAULTS = { ates: true, muhur: true, gezegen: true, patlatma: true, simsek: true, iz: true,
    kontroller: true, yuz: true, kitaplik: true, sesler: true, rafAtesYok: true, gezegenSabit: "" };

  class FxSettings {
    constructor() {
      this.v = Object.assign({}, DEFAULTS);
      try { Object.assign(this.v, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) { /* gizli pencere */ }
      this.onChange = null;
    }

    get(k) { return !!this.v[k]; }

    set(k, val) {
      this.v[k] = val;
      try { localStorage.setItem(KEY, JSON.stringify(this.v)); } catch (e) { /* yoksay */ }
      this.onChange && this.onChange(k, val);
    }

    // panel: <div> icine onay kutulari + gezegen secimi
    render(panel) {
      panel.innerHTML = "<h3>EFEKTLER</h3>";
      for (const [k, label] of ITEMS) {
        const row = document.createElement("label");
        row.className = "fxrow";
        row.innerHTML = `<input type="checkbox" ${this.v[k] ? "checked" : ""}> <span>${label}</span>`;
        row.querySelector("input").addEventListener("change", (e) => this.set(k, e.target.checked));
        panel.appendChild(row);
      }
      const sel = document.createElement("label");
      sel.className = "fxrow";
      const opts = [["", "Her çimdikte sıradaki"], ...JEL.PLANETS.map((p) => [p, JEL.PLANET_NAMES[p]])];
      sel.innerHTML = `<span>Gezegen</span> <select>${opts.map(([v, n]) =>
        `<option value="${v}" ${this.v.gezegenSabit === v ? "selected" : ""}>${n}</option>`).join("")}</select>`;
      sel.querySelector("select").addEventListener("change", (e) => this.set("gezegenSabit", e.target.value));
      panel.appendChild(sel);
      const hint = document.createElement("p");
      hint.className = "fxhint";
      hint.textContent = "Tuşlar: L arayüz · E efektler · F yüz · K kitaplık ayarı · B elimdeki kitap · D iskelet · M ses · C kamera · Esc kapat";
      panel.appendChild(hint);
    }
  }

  JEL.FxSettings = FxSettings;
})();
