"""Stark Ekibi sayfasi (/ekip) - "sahne / podcast": konusan uye ortada buyuk, digerleri altta sirada.

Iki mod:
  - SOHBET: alttaki seritten bir uyeye dokun -> yaz/konus -> persona kendi modeliyle ve kendi
    sesiyle yanitlar. Ekip koprusu acikken persona once bir ekip arkadasina danisabilir.
  - TOPLANTI: birden cok uye sec -> soru sor -> sabit sira yok: her konusmadan sonra sozu o an
    katkisi en anlamli olana sunucu verir (/api/team/council/next). Uyeler birbirinin sozunu
    bekler (sesler ust uste binmez); sonraki konusmaci o sirada arka planda hazirlanir ve
    seritte "sirada" diye yanar. En sonda secilen uye kararlari ozetler.
Sahnede konusanin buyuk avatari kendi renginde sesle birlikte parlar; soyledigi cumle kelime
kelime (karaoke gibi) akar. Gorunum Zoey OS dili: siyah zemin, turuncu vurgu, cam paneller.
J.A.R.V.I.S. canli beyne gider ve PC'den kendi Live sesiyle konusur (toplantiya katilamaz).
"""

from __future__ import annotations

_HTML = r"""<!doctype html><html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#000000">
<title>Stark Ekibi</title>
<link rel="icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;700;900&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#000;--o:#ff6d00;--accent:#ff8c42;--tx:#fffffff0;--tx2:#ffffff9e;--tx3:#ffffff57;
--line:#ffffff14;--line2:#ffffff26;--bad:#ef4444;--good:#10b981;
--glass:linear-gradient(165deg,#ffffff1a 0%,#ffffff09 30%,#ffffff03 58%,#ffffff0d 100%),#10101661;
--sans:"Onest",-apple-system,"Segoe UI",Roboto,sans-serif;--mono:"JetBrains Mono","Cascadia Code",Consolas,monospace;
--side:390px;--bar:72px}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;background:var(--bg);overflow:hidden}
body{color:var(--tx2);font-family:var(--sans);font-size:14px;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit}
.glass{background:var(--glass);-webkit-backdrop-filter:blur(22px) saturate(170%);backdrop-filter:blur(22px) saturate(170%);
border:1px solid var(--line);box-shadow:inset 0 1px 0 #ffffff29,0 12px 34px #00000073}

/* --- sahne --- */
#stage{position:fixed;top:0;left:0;right:var(--side);bottom:var(--bar);display:flex;flex-direction:column;
align-items:center;padding:58px 24px 10px;overflow:hidden}
.spot{flex:1;min-height:0;width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;
--c:var(--o);--g:0}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--c);opacity:.85}
.tag.idle{color:var(--tx3)}
.ava-wrap{position:relative;display:grid;place-items:center;width:210px;height:210px}
.ava-wrap::before{content:"";position:absolute;inset:-40px;border-radius:50%;pointer-events:none;
background:radial-gradient(circle,color-mix(in srgb,var(--c) 30%,transparent) 0%,transparent 62%);
opacity:calc(.25 + var(--g)*.75);transform:scale(calc(.85 + var(--g)*.35));transition:opacity .2s}
.ava{position:relative;display:grid;place-items:center;width:150px;height:150px;border-radius:50%;
border:2px solid var(--c);font-family:var(--sans);font-weight:900;font-size:52px;letter-spacing:-.02em;color:var(--c);
background:radial-gradient(circle at 35% 28%,color-mix(in srgb,var(--c) 30%,#000) 0%,#0b0b0e 72%);
box-shadow:inset 0 1px 0 #ffffff29,0 0 calc(18px + var(--g)*70px) color-mix(in srgb,var(--c) calc(25% + var(--g)*55%),transparent);
transform:scale(calc(1 + var(--g)*.06))}
.spot.empty .ava{border-style:dashed;opacity:.35}
.spot.think .ava{animation:ring 1.4s ease-in-out infinite}
@keyframes ring{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--c) 55%,transparent)}50%{box-shadow:0 0 0 16px transparent}}
.who-name{font-family:var(--sans);font-weight:900;font-size:34px;letter-spacing:-.01em;color:var(--c);line-height:1.1;
text-shadow:0 0 28px color-mix(in srgb,var(--c) 40%,transparent);text-align:center}
.who-meta{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--tx3);text-align:center}
#line{max-width:820px;max-height:calc(1.45em * 4);overflow:hidden;text-align:center;font-family:var(--sans);
font-weight:500;font-size:26px;line-height:1.45;color:var(--tx);scroll-behavior:smooth}
#line .w{opacity:.22;transition:opacity .18s}
#line .w.on{opacity:1}
#line.hint{font-size:16px;color:var(--tx3);font-weight:400}
.wave{display:flex;align-items:center;gap:5px;height:34px}
.wave span{display:block;width:3.5px;height:var(--h);border-radius:2px;background:var(--c);opacity:.9;
box-shadow:0 0 8px color-mix(in srgb,var(--c) 45%,transparent);transform:scaleY(.2);transition:transform 90ms linear}
.spot:not(.talk) .wave span{opacity:.25}
/* --- uye seridi --- */
#strip{display:flex;gap:8px;max-width:100%;overflow-x:auto;padding:8px 6px 6px;scrollbar-width:none}
#strip::-webkit-scrollbar{display:none}
.seat{flex:none;display:flex;flex-direction:column;align-items:center;gap:6px;width:64px;background:none;border:0;cursor:pointer;
opacity:.42;transition:opacity .2s}
.seat:hover,.seat.sel,.seat.talk,.seat.think{opacity:1}
.seat.off{opacity:.15;cursor:not-allowed}
.seat i{display:grid;place-items:center;width:52px;height:52px;border-radius:50%;font-style:normal;font-weight:900;font-size:16px;
color:var(--c);border:1px solid var(--line2);background:radial-gradient(circle at 35% 28%,color-mix(in srgb,var(--c) 22%,#000) 0%,#0b0b0e 75%)}
.seat.sel i{border:2px solid var(--c)}
.seat.talk i{border:2px solid var(--c);box-shadow:0 0 22px color-mix(in srgb,var(--c) 60%,transparent)}
.seat.think i{border:2px solid var(--c);animation:ring 1.2s ease-in-out infinite}
.seat b{font-family:var(--mono);font-size:9px;font-weight:400;letter-spacing:.06em;color:var(--tx2);white-space:nowrap;
max-width:64px;overflow:hidden;text-overflow:ellipsis}
.seat em{font-style:normal;font-family:var(--mono);font-size:8px;letter-spacing:.14em;text-transform:uppercase;color:var(--c);
height:10px;margin-top:-4px}
.corner{position:fixed;width:350px;height:350px;border-radius:50%;pointer-events:none;top:-100px}
.corner.l{left:-100px;background:radial-gradient(circle,#ff6d000f 0%,#0000 70%)}
.corner.r{right:calc(var(--side) - 100px);background:radial-gradient(circle,#ff6d000d 0%,#0000 70%)}
@media (prefers-reduced-motion:reduce){.spot.think .ava,.seat.think i{animation:none}#line .w{transition:none}}

/* --- ust serit --- */
header{position:fixed;top:14px;left:16px;right:calc(var(--side) + 16px);display:flex;align-items:center;gap:10px;
flex-wrap:wrap;z-index:5;pointer-events:none}
header>*{pointer-events:auto}
.logo{font-family:var(--mono);font-weight:700;letter-spacing:.3em;color:var(--o);font-size:15px;
text-shadow:0 0 20px #ff6d0099,0 0 40px #ff6d004d}
.back{color:var(--tx3);font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-decoration:none;
border:1px solid var(--line);border-radius:999px;padding:4px 10px}
.status{margin-left:auto;font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--o)}

/* --- yan panel --- */
#side{position:fixed;top:0;right:0;bottom:var(--bar);width:var(--side);display:flex;flex-direction:column;gap:10px;
padding:14px 14px 10px;z-index:4}
.tabs{display:flex;gap:6px}
.tab,.tog{border:1px solid var(--line);background:#ffffff08;border-radius:999px;padding:5px 12px;cursor:pointer;
font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--tx2);
transition:border-color .15s,color .15s,background .15s}
.tab:hover,.tog:hover{border-color:var(--line2);color:var(--tx)}
.tab.on,.tog.on{background:#ff8c421a;border-color:#ff8c424d;color:var(--accent)}
.tog.paid.on{background:#ef44441a;border-color:#ef44444d;color:var(--bad)}
.opts{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--tx3)}
.opts select{background:#0b0b0e;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:4px 6px;
font-family:var(--mono);font-size:11px}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 var(--c)}50%{box-shadow:0 0 0 5px transparent}}
.chat{flex:1;min-height:0;display:flex;flex-direction:column;border-radius:14px;padding:12px}
.chat h2{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;
color:var(--c,var(--o));font-weight:700}
#log{flex:1;min-height:0;display:flex;flex-direction:column;gap:8px;overflow-y:auto;padding-right:2px}
#log::-webkit-scrollbar{width:6px}#log::-webkit-scrollbar-thumb{background:#ffffff1c;border-radius:3px}
.msg{padding:8px 11px;border-radius:12px;border:1px solid var(--line);background:#ffffff06;line-height:1.5;
max-width:94%;overflow-wrap:anywhere;color:var(--tx);font-size:13px}
.msg .who{font-family:var(--mono);font-size:9px;letter-spacing:.12em;font-weight:700;color:var(--c);margin-bottom:3px;text-transform:uppercase}
.msg.user{align-self:flex-end;background:#ff8c4212;border-color:#ff8c4238}
.msg.ai{align-self:flex-start;border-left:2px solid var(--c)}
.msg.bridge{align-self:flex-start;margin-left:16px;max-width:88%;font-size:12px;border-style:dashed;border-left:2px solid var(--c)}
.msg.link{align-self:flex-start;margin-left:16px;font-family:var(--mono);font-size:10px;color:var(--tx3);border:0;background:none;padding:0 4px}
.msg.err{align-self:flex-start;border-color:#ef44444d;color:var(--bad);font-size:12px}
.msg.sum{border-left-width:4px;box-shadow:0 0 18px color-mix(in srgb,var(--c) 16%,transparent)}
.msg .meta{font-family:var(--mono);font-size:9px;color:var(--tx3);margin-top:4px;letter-spacing:.06em}
.msg .src a{color:var(--accent);font-size:11px;margin-right:8px}
.empty{color:var(--tx3);font-size:12px;line-height:1.6}

/* --- giris cubugu --- */
.bar{position:fixed;left:0;right:0;bottom:0;height:var(--bar);display:flex;align-items:center;justify-content:center;
padding:0 16px env(safe-area-inset-bottom);z-index:6;background:linear-gradient(#0000,#000 40%)}
.bar .in{display:flex;gap:8px;width:100%;max-width:980px}
#inp{flex:1;min-width:0;border-radius:999px;color:var(--tx);padding:12px 18px;font-size:15px;font-family:var(--sans);outline:none}
#inp:focus{border-color:#ff6d004d}
.icon{flex:none;width:46px;height:46px;border-radius:50%;cursor:pointer;font-size:17px;color:var(--accent);
display:grid;place-items:center;border:1px solid #ff8c4266;box-shadow:inset 0 1px 0 #ffffff24,0 0 16px #ff8c4233}
.icon:hover{box-shadow:inset 0 1px 0 #ffffff24,0 0 28px #ff8c4273}
.icon.rec{border-color:var(--bad);color:var(--bad);animation:pulse 1s infinite;--c:var(--bad)}

@media (max-width:760px){
  :root{--side:0px}
  #stage{bottom:calc(46vh + var(--bar));padding:52px 12px 4px}
  .ava-wrap{width:96px;height:96px}.ava{width:74px;height:74px;font-size:26px}.wave{height:26px}
  .who-name{font-size:22px}#line{font-size:17px;min-height:2.9em;flex:none}.spot{gap:6px}
  .who-meta{display:none}.tag{font-size:9px}
  #side{left:0;width:auto;top:auto;height:46vh;padding:8px 10px}
  header{right:16px}
  .corner.r{right:-100px}
}
</style></head><body>
<main id="stage">
  <section class="spot empty" id="spot">
    <div class="tag idle" id="tag">Sahne boş</div>
    <div class="ava-wrap"><div class="ava" id="ava"></div></div>
    <div><div class="who-name" id="whoName"></div><div class="who-meta" id="whoMeta"></div></div>
    <p id="line" class="hint" aria-live="polite">Alttan bir üyeye dokun.</p>
    <div class="wave" id="wave" aria-hidden="true"></div>
  </section>
  <nav id="strip" aria-label="Ekip üyeleri"><span class="empty">yükleniyor…</span></nav>
</main>
<div class="corner l"></div><div class="corner r"></div>
<header><span class="logo">STARK EKİBİ</span><a class="back" href="/">&larr; KONSOL</a>
<span class="status" id="status"></span></header>
<aside id="side">
  <div class="tabs"><button class="tab on" id="tabChat">Sohbet</button><button class="tab" id="tabMeet">Toplantı</button>
  <button class="tog on" id="tts" title="Yanıtları sesli oku">Ses</button></div>
  <div class="opts" id="chatOpts">
    <button class="tog on" id="tConsult" title="Yapay zekâ gerekirse ekip arkadaşına danışsın">Ekip köprüsü</button>
    <button class="tog paid" id="tPaid" title="Ücretli V.E.R.O.N.I.C.A.'ya danışılabilsin">V.E.R.O.N.I.C.A. danışılabilir</button>
  </div>
  <div class="opts" id="meetOpts" style="display:none">
    <span>En çok konuşma</span><select id="talks"><option>4</option><option selected>6</option><option>8</option></select>
    <span>Özetleyen</span><select id="summ"></select>
  </div>
  <div class="chat glass" id="chat"><h2 id="title">Bir yapay zekâ seç</h2>
    <div id="log"><div class="empty">Alttaki şeritten bir üyeye dokun, sonra yaz ya da mikrofona konuş.</div></div></div>
</aside>
<div class="bar"><div class="in">
  <input id="inp" class="glass" placeholder="Bir yapay zekâ seç…" autocomplete="off">
  <button class="icon glass" id="mic" title="Mikrofon">&#127908;</button>
  <button class="icon glass" id="stop" title="Durdur">&#9632;</button>
  <button class="icon glass" id="send" title="Gönder">&#10148;</button>
</div></div>
<script>
let KEY=new URLSearchParams(location.search).get('key')||'';
try{ if(KEY) localStorage.setItem('jv_key',KEY); else KEY=localStorage.getItem('jv_key')||''; }catch(e){}
const q=s=>document.querySelector(s);
function api(path,body){return fetch(path+(path.includes('?')?'&':'?')+'key='+encodeURIComponent(KEY),
  body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})
  .then(r=>r.json().then(j=>({ok:r.ok,status:r.status,j})));}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function pref(k,d){try{const v=localStorage.getItem(k);return v===null?d:v==='1';}catch(e){return d;}}
function setPref(k,v){try{localStorage.setItem(k,v?'1':'0');}catch(e){}}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

let personas=[],P={},sel=null,mode='chat';
let ttsOn=pref('team_tts',true),consultOn=pref('team_consult',true),paidOn=false;
let members=['pepper','homer','karen'],meetRun=0;
const logs={};   // 'chat:<key>' | 'meet' -> [{kind,persona,text,meta,sources}]
const st={};     // key -> {talk,think}
function bindTog(id,get,set){const b=q(id);b.classList.toggle('on',get());b.onclick=()=>{set(!get());b.classList.toggle('on',get());};}
bindTog('#tts',()=>ttsOn,v=>{ttsOn=v;setPref('team_tts',v);if(!v)stopAudio();});
bindTog('#tConsult',()=>consultOn,v=>{consultOn=v;setPref('team_consult',v);});
bindTog('#tPaid',()=>paidOn,v=>{paidOn=v;});
function status(t){q('#status').textContent=t||'';}

// ------------------------------------------------------------------ sahne
// Ortada spot (konusan > dusunen > son konusan > sohbette secili), altta uye seridi.
const BARS=[7,9,14,17,22,26,15,19,10,16,20,24,13,18,24,14,11,8];   // zoeyos.com dalga cubuklari
const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;
function initials(name){const w=String(name).split(/\s+/).filter(Boolean);
  if(w.length>1)return (w[0][0]+w[1][0]).toUpperCase();
  return String(name).replace(/[^A-Za-zÇĞİÖŞÜçğıöşü]/g,'').slice(0,2).toUpperCase();}
const stageUI={
  cur:null,last:null,amp:0,target:0,words:[],shown:0,timer:0,src:null,t0:0,text:'',
  build(list){
    q('#strip').innerHTML=list.map(p=>`<button class="seat" data-k="${esc(p.key)}" style="--c:${esc(p.color)}"
      title="${esc(p.name)} · ${esc(p.role)} · ${esc(p.model)}"><i>${esc(initials(p.name))}</i><b>${esc(p.name.replace(/\./g,""))}</b><em></em></button>`).join('');
    q('#strip').querySelectorAll('.seat').forEach(b=>b.onclick=()=>this.onPick&&this.onPick(b.dataset.k));
    q('#wave').innerHTML=BARS.map(h=>`<span style="--h:${h}px"></span>`).join('');
    this.loop();
  },
  state(k,s){
    const b=q('.seat[data-k="'+k+'"]');
    if(b){b.classList.toggle('sel',s.sel);b.classList.toggle('talk',s.talk);b.classList.toggle('think',s.think&&!s.talk);
      b.classList.toggle('off',s.off);b.querySelector('em').textContent=s.talk?'konuşuyor':(s.think?(mode==='meet'?'sırada':'düşünüyor'):'');
      if(s.talk)b.scrollIntoView({inline:'center',block:'nearest',behavior:REDUCED?'auto':'smooth'});}
    if(!s.talk&&k===this.cur)this.finish();
    this.render();
  },
  level(k,a){if(k===this.cur)this.target=a;},
  focus(k){},
  onPick:null,
  // Spotta kim duracak: konusan > dusunen > son konusan (cumlesi kalir) > sohbette secili
  pickKey(){
    const ks=personas.map(p=>p.key);
    return ks.find(k=>st[k]&&st[k].talk)||ks.find(k=>st[k]&&st[k].think)||this.last||(mode==='chat'&&sel?sel.key:null);
  },
  render(){
    const k=this.pickKey(),p=P[k],spot=q('#spot'),s=st[k]||{};
    spot.classList.toggle('empty',!p);spot.classList.toggle('talk',!!s.talk);spot.classList.toggle('think',!!s.think&&!s.talk);
    const tag=q('#tag');
    if(!p){tag.className='tag idle';tag.textContent='Sahne boş';q('#ava').textContent='';q('#whoName').textContent='';
      q('#whoMeta').textContent='';this.hint(mode==='meet'?'Alttan üyeleri seç, sonra soruyu yaz.':'Alttan bir üyeye dokun.');this.cur=null;return;}
    spot.style.setProperty('--c',p.color);
    tag.className='tag'+(s.talk||s.think?'':' idle');
    tag.textContent=s.talk?'Şimdi konuşuyor':(s.think?(mode==='meet'?'Söz alıyor · düşünüyor…':'Düşünüyor…'):(k===this.last?'Son konuşan':'Seçili'));
    if(k!==this.cur){
      this.cur=k;q('#ava').textContent=initials(p.name);q('#whoName').textContent=p.name;
      q('#whoMeta').textContent=(p.provider==='live'?'canlı ses':p.provider)+' · '+p.model;
      if(k!==this.last||!this.words.length)this.hint(s.think?'…':'Yaz ya da mikrofona bas.');
    }
  },
  hint(t){clearInterval(this.timer);this.words=[];const l=q('#line');l.className='hint';l.textContent=t;},
  // Karaoke: kelimeler sesin ilerleyisiyle acilir. src: <audio> (sure), 'boundary' (tarayici sesi) ya da null (tahmin)
  say(k,text,src){
    clearInterval(this.timer);this.last=k;this.text=text;this.src=src;this.t0=performance.now();this.shown=0;
    const l=q('#line');l.className='';l.scrollTop=0;
    l.innerHTML=String(text).split(/(\s+)/).map(w=>/^\s+$/.test(w)?w:`<span class="w">${esc(w)}</span>`).join('');
    this.words=[...l.querySelectorAll('.w')];
    this.render();
    if(REDUCED){this.reveal(1);return;}
    this.timer=setInterval(()=>{let p;
      const a=this.src;
      if(a&&a.duration&&isFinite(a.duration))p=a.currentTime/a.duration/.82;   // zoeyos.com yontemi
      else if(a==='boundary')return;                                           // onboundary ilerletir
      else p=(performance.now()-this.t0)/(this.text.length*65);
      this.reveal(p);},40);
  },
  sayChar(i){const n=this.text.slice(0,i).split(/\s+/).filter(Boolean).length+1;this.reveal(n/this.words.length);},
  reveal(p){
    const n=Math.max(0,Math.min(this.words.length,Math.ceil(p*this.words.length)));
    if(n===this.shown)return;
    for(let i=this.shown;i<n;i++)this.words[i].classList.add('on');
    this.shown=n;const w=this.words[n-1],l=q('#line');
    if(w&&w.offsetTop+w.offsetHeight>l.scrollTop+l.clientHeight)l.scrollTop=w.offsetTop-l.clientHeight/2;
    if(n>=this.words.length)clearInterval(this.timer);
  },
  finish(){this.reveal(1);this.target=0;},
  loop(){
    const tick=()=>{this.amp=this.target>this.amp?this.amp*.15+this.target*.85:this.amp*.82+this.target*.18;
      const spot=q('#spot');spot.style.setProperty('--g',this.amp.toFixed(3));
      if(spot.classList.contains('talk'))q('#wave').querySelectorAll('span').forEach((b,i)=>
        b.style.transform=`scaleY(${.25+this.amp*(.85+.4*Math.sin(i*2.1))})`);
      else q('#wave').querySelectorAll('span').forEach(b=>b.style.transform='');
      requestAnimationFrame(tick);};
    requestAnimationFrame(tick);
  },
};
window.teamRoom=stageUI;
function room(){return window.teamRoom||null;}
function paintSeat(k){
  const s=st[k]||{},inSel=mode==='chat'?(!!sel&&sel.key===k):members.includes(k);
  const off=mode==='meet'&&P[k]&&P[k].provider==='live';
  const r=room();if(r)r.state(k,{talk:!!s.talk,think:!!s.think,sel:inSel,off});
}
function setSt(k,patch){st[k]=Object.assign(st[k]||{},patch);paintSeat(k);}
function paintAll(){personas.forEach(p=>paintSeat(p.key));}
window.roomReady=()=>{const r=room();if(!r||!personas.length)return;r.build(personas);r.onPick=pick;paintAll();};

// ------------------------------------------------------------------ uyeler
function pick(k){if(!P[k])return;mode==='chat'?select(k):toggleMember(k);}
function refresh(){
  paintAll();
  if(mode==='meet'){
    const s=q('#summ'),cur=s.value;
    s.innerHTML=personas.filter(p=>p.provider!=='live').map(p=>`<option value="${esc(p.key)}">${esc(p.name)}${p.paid?' ($)':''}</option>`).join('');
    s.value=cur||'friday';
  }
}
function toggleMember(k){
  if(P[k].provider==='live')return;
  const i=members.indexOf(k); if(i>=0)members.splice(i,1); else members.push(k);
  refresh();renderLog();
}
function select(k){
  sel=P[k];if(!sel)return;
  if(stageUI.last!==k)stageUI.last=null;
  q('#chat').style.setProperty('--c',sel.color);
  const r=room();if(r)r.focus(k);
  refresh();renderLog();q('#inp').focus();
}
function setMode(m){
  mode=m;q('#tabChat').classList.toggle('on',m==='chat');q('#tabMeet').classList.toggle('on',m==='meet');
  q('#chatOpts').style.display=m==='chat'?'':'none';q('#meetOpts').style.display=m==='meet'?'':'none';
  if(m==='meet')q('#chat').style.setProperty('--c','var(--o)');else if(sel)q('#chat').style.setProperty('--c',sel.color);
  stageUI.last=null;refresh();renderLog();
}
q('#tabChat').onclick=()=>setMode('chat');q('#tabMeet').onclick=()=>setMode('meet');

// ------------------------------------------------------------------ kayit
function logKey(){return mode==='meet'?'meet':(sel?'chat:'+sel.key:'');}
function renderLog(){
  const k=logKey();
  if(mode==='meet'){
    q('#title').textContent='Ekip toplantısı · '+(members.map(m=>P[m]&&P[m].name).filter(Boolean).join(', ')||'üye seç');
    q('#inp').placeholder='Toplantıya bir soru sor…';
  }else if(sel){q('#title').textContent=sel.name+' · '+sel.model;q('#inp').placeholder=sel.name+"'a yaz…";}
  else{q('#title').textContent='Bir yapay zekâ seç';q('#inp').placeholder='Bir yapay zekâ seç…';}
  const items=logs[k]||[];
  if(!items.length){q('#log').innerHTML='<div class="empty">'+(mode==='meet'
    ?'Alttaki şeritten üyeleri seç, sonra soruyu yaz. Sabit sıra yok: söz, o an katkısı en anlamlı olana geçer; herkes ötekinin sözünü bitirmesini bekler.'
    :(sel?esc(sel.name)+' hazır. Yaz ya da mikrofona bas.':'Alttaki şeritten bir üyeye dokun.'))+'</div>';return;}
  q('#log').innerHTML=items.map(m=>{
    const p=P[m.persona]||{},c=p.color||'var(--o)';
    if(m.kind==='err')return `<div class="msg err">${esc(m.text)}</div>`;
    if(m.kind==='user')return `<div class="msg user">${esc(m.text)}</div>`;
    if(m.kind==='link')return `<div class="msg link" style="--c:${esc(c)}">&#8627; ${esc(m.text)}</div>`;
    const src=(m.sources||[]).filter(s=>s.url).slice(0,4).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title||'kaynak')}</a>`).join('');
    const cls=m.kind==='bridge'?'bridge':('ai'+(m.kind==='sum'?' sum':''));
    return `<div class="msg ${cls}" style="--c:${esc(c)}"><div class="who">${esc(p.name||'')}${m.kind==='sum'?' · özet':''}</div>${esc(m.text)}${src?'<div class="src">'+src+'</div>':''}${m.meta?'<div class="meta">'+esc(m.meta)+'</div>':''}</div>`;
  }).join('');
  q('#log').scrollTop=q('#log').scrollHeight;
}
function push(k,m){(logs[k]=logs[k]||[]).push(m);if(logKey()===k)renderLog();}

// ------------------------------------------------------------------ ses: tek oynatici, ust uste binmez
// Her konusma bir Promise doner (bitince cozulur); toplanti bir sonrakini bunu bekleyerek baslatir.
let queue=[],playing=null,audio=null,actx=null,analyser=null,raf=0;
function ensureCtx(){
  try{if(!actx){actx=new (window.AudioContext||window.webkitAudioContext)();analyser=actx.createAnalyser();
    analyser.fftSize=512;analyser.connect(actx.destination);} if(actx.state==='suspended')actx.resume();}catch(e){actx=null;}
}
function meter(key){
  cancelAnimationFrame(raf);const buf=analyser?new Uint8Array(analyser.fftSize):null;
  const tick=()=>{let a=0;
    if(buf){analyser.getByteTimeDomainData(buf);let s=0;for(let i=0;i<buf.length;i++){const v=(buf[i]-128)/128;s+=v*v;}
      a=Math.min(1,Math.sqrt(s/buf.length)*3.2);}
    else a=.35+.25*Math.sin(performance.now()/90);
    const r=room();if(r)r.level(key,a);raf=requestAnimationFrame(tick);};
  tick();
}
function stopAudio(){
  const pend=queue.concat(playing?[playing]:[]);queue=[];
  if(audio){audio.onended=audio.onerror=null;audio.pause();audio=null;}
  if('speechSynthesis' in window)speechSynthesis.cancel();
  cancelAnimationFrame(raf);personas.forEach(p=>{if(st[p.key]&&st[p.key].talk)setSt(p.key,{talk:false});});
  playing=null;pend.forEach(it=>it.resolve());
}
function speak(key,text,dataUrl){
  return new Promise(resolve=>{
    if(!ttsOn||!text){resolve();return;}
    queue.push({key,text,dataUrl,resolve});if(!playing)next();
  });
}
function next(){
  const it=queue.shift();playing=it||null;if(!it)return;
  let finished=false;
  const done=()=>{if(finished)return;finished=true;cancelAnimationFrame(raf);const r=room();if(r)r.level(it.key,0);
    setSt(it.key,{talk:false});audio=null;playing=null;it.resolve();setTimeout(next,250);};
  setSt(it.key,{talk:true});const r=room();if(r)r.focus(it.key);
  if(it.dataUrl){
    audio=new Audio(it.dataUrl);audio.onended=audio.onerror=done;
    try{if(actx&&analyser)actx.createMediaElementSource(audio).connect(analyser);}catch(e){}
    meter(it.key);if(r)r.say(it.key,it.text,audio);
    audio.play().catch(()=>{cancelAnimationFrame(raf);browserSay(it,done);});
  }else browserSay(it,done);
}
function browserSay(it,done){
  if(!('speechSynthesis' in window)){done();return;}
  const u=new SpeechSynthesisUtterance(it.text);u.lang='tr-TR';
  const v=speechSynthesis.getVoices().find(v=>v.lang&&v.lang.startsWith('tr'));if(v)u.voice=v;
  u.pitch=1;u.rate=1;meter(it.key);u.onend=u.onerror=done;
  const r=room();if(r){r.say(it.key,it.text,'boundary');u.onboundary=e=>r.sayChar(e.charIndex);}
  speechSynthesis.speak(u);
}

// ------------------------------------------------------------------ sohbet (+ ekip koprusu)
let waitingJarvis=false;
async function sendChat(text){
  if(!sel){alert('Önce bir yapay zekâ seç.');return;}
  const p=sel,k='chat:'+p.key;
  const history=(logs[k]||[]).filter(m=>m.kind==='user'||m.kind==='ai').slice(-8)
    .map(m=>({role:m.kind==='user'?'user':'assistant',text:m.text}));
  push(k,{kind:'user',text});
  setSt(p.key,{think:true});status(p.name+' düşünüyor…');
  try{
    const r=await api('/api/team/ask',{persona:p.key,text,history,consult:consultOn,allow_paid:paidOn});
    if(!r.ok){push(k,{kind:'err',text:(r.j&&r.j.error)||('hata '+r.status)});return;}
    const res=r.j;
    if(res.via==='live'){waitingJarvis=true;push(k,{kind:'ai',persona:'jarvis',text:'(PC hoparlöründen yanıtlıyor…)',meta:'canlı oturum'});return;}
    for(const c of res.consults||[]){
      const to=P[c.to];
      push(k,{kind:'link',persona:c.to,text:p.name+' → '+(to?to.name:c.to)+': '+c.question});
      if(c.text){push(k,{kind:'bridge',persona:c.to,text:c.text,sources:c.sources,meta:c.model||''});speak(c.to,c.text,c.audio);}
      else push(k,{kind:'err',text:(to?to.name:c.to)+' danışılamadı: '+(c.error||'?')});
    }
    if(res.error&&!res.text){push(k,{kind:'err',text:p.name+' yanıt vermedi: '+res.error});return;}
    push(k,{kind:'ai',persona:p.key,text:res.text,sources:res.sources,meta:(res.model||'')+(res.audio?' · ses':'')});
    speak(p.key,res.text,res.audio);
  }catch(e){push(k,{kind:'err',text:'bağlantı hatası: '+e});}
  finally{setSt(p.key,{think:false});status('');}
}

// ------------------------------------------------------------------ toplanti: sirasiz, soz bekleyen
async function sendMeet(topic){
  const seats=members.filter(m=>P[m]&&P[m].provider!=='live');
  if(seats.length<2){alert('Toplantı için en az 2 üye seç.');return;}
  const summ=q('#summ').value,maxTalks=+q('#talks').value,run=++meetRun;
  if(P[summ].paid&&!seats.includes(summ)&&!confirm('Özetleyen V.E.R.O.N.I.C.A. ücretli. Devam?'))return;
  stopAudio();logs.meet=[];push('meet',{kind:'user',text:topic});
  const transcript=[];let last=null;
  const live=()=>run===meetRun;

  // Sozu kime verecegini sorar ve o uyenin konusmasini hazirlar (ses calarken arka planda kosar).
  async function prepare(){
    let key=null,reason='';
    try{const n=await api('/api/team/council/next',{topic,transcript,members:seats,last});
      if(!live())return null;
      if(n.ok){key=n.j.next;reason=n.j.reason||'';if(!key)return {done:true,reason};}}
    catch(e){}
    if(!key)key=seats.find(k=>k!==last&&!transcript.some(t=>t.persona===k))||seats.find(k=>k!==last);
    if(!key||!live())return null;
    setSt(key,{think:true});
    try{const r=await api('/api/team/council/turn',{persona:key,topic,transcript,final:false});
      return {key,reason,r};}
    catch(e){return {key,reason,r:{ok:false,status:0,j:{error:'bağlantı hatası: '+e}}};}
    finally{setSt(key,{think:false});}
  }
  function record(it,kind){
    const res=it.r.j||{};
    if(!it.r.ok||!res.text){push('meet',{kind:'err',text:P[it.key].name+': '+(res.error||('hata '+it.r.status))});return null;}
    transcript.push({persona:it.key,text:res.text});last=it.key;
    push('meet',{kind,persona:it.key,text:res.text,sources:res.sources,meta:[res.model,it.reason&&('söz: '+it.reason)].filter(Boolean).join(' · ')});
    return res;
  }

  status('Toplantı sürüyor…');
  let pending=prepare();
  for(let i=0;i<maxTalks;i++){
    const it=await pending;
    if(!live())return;
    if(!it||it.done){if(it&&it.reason)push('meet',{kind:'link',persona:summ,text:'söz kapandı: '+it.reason});break;}
    const res=record(it,'ai');
    pending=i+1<maxTalks?prepare():Promise.resolve(null);   // sonraki konusmaci bu konusma calarken hazirlanir
    if(res)await speak(it.key,res.text,res.audio);            // ama bu ses bitmeden baslamaz
    if(!live())return;
  }
  if(!live())return;
  status('Özetleniyor…');setSt(summ,{think:true});
  try{
    const r=await api('/api/team/council/turn',{persona:summ,topic,transcript,final:true});
    if(!live())return;
    setSt(summ,{think:false});
    const res=record({key:summ,reason:'',r},'sum');
    if(res)await speak(summ,res.text,res.audio);
  }catch(e){push('meet',{kind:'err',text:'bağlantı hatası: '+e});}
  finally{setSt(summ,{think:false});if(live())status('');}
}

async function send(text){
  text=(text||'').trim();if(!text)return;q('#inp').value='';ensureCtx();
  if(mode==='meet')return sendMeet(text);
  return sendChat(text);
}
q('#send').onclick=()=>send(q('#inp').value);
q('#inp').onkeydown=e=>{if(e.key==='Enter')send(q('#inp').value);};
q('#stop').onclick=()=>{meetRun++;stopAudio();status('');personas.forEach(p=>setSt(p.key,{think:false}));};

// ------------------------------------------------------------------ mikrofon (Chrome/Edge)
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;let rec=null,recOn=false;
q('#mic').onclick=()=>{
  if(!SR){alert('Bu tarayıcı ses tanımayı desteklemiyor (Chrome/Edge kullan).');return;}
  if(recOn){rec&&rec.stop();return;}
  if(mode==='chat'&&!sel){alert('Önce bir yapay zekâ seç.');return;}
  stopAudio();ensureCtx();
  rec=new SR();rec.lang='tr-TR';rec.interimResults=false;rec.continuous=false;
  rec.onresult=e=>{const t=e.results[0][0].transcript;q('#inp').value=t;send(t);};
  rec.onend=rec.onerror=()=>{recOn=false;q('#mic').classList.remove('rec');};
  recOn=true;q('#mic').classList.add('rec');rec.start();
};

// ------------------------------------------------------------------ J.A.R.V.I.S. (SSE)
function connectSSE(){const ev=new EventSource('/api/events?key='+encodeURIComponent(KEY));
  ev.onmessage=e=>{try{const evt=JSON.parse(e.data);
    if(evt.kind==='transcript'&&evt.data.who==='jarvis'&&waitingJarvis)
      push('chat:jarvis',{kind:'ai',persona:'jarvis',text:evt.data.text,meta:'gemini-2.5-flash-native-audio · canlı ses'});
  }catch(x){}};
  ev.onerror=()=>{ev.close();setTimeout(connectSSE,3000);};}

api('/api/team').then(r=>{
  if(!r.ok){q('#strip').innerHTML='<div class="empty">Erişim yok ('+r.status+'). Adrese ?key=... ekle.</div>';return;}
  personas=r.j.personas||[];P=Object.fromEntries(personas.map(p=>[p.key,p]));
  if(!r.j.tts)q('#tts').title='Sunucu sesi kapalı: tarayıcı sesi kullanılır';
  window.roomReady();refresh();connectSSE();
});
if('speechSynthesis' in window)speechSynthesis.getVoices();
</script>
</body></html>"""


def render_team_page() -> str:
    return _HTML
