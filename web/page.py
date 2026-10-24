"""Mobil-uyumlu tek sayfa web konsolu (Iron Man HUD temasi).

Telefondan JARVIS ile YAZILI ve SESLI (cift yonlu) gorusme:
  - "Telefon gorusmesi" modu: mikrofon surekli dinler, JARVIS yaniti telefonda
    sesli okunur (Web Speech API - SpeechSynthesis). Konusurken mikrofon durur (eko).
  - "Uzak mod": PC'nin mikrofonu + hoparloru susturulur; gorusme tamamen telefonden.
"""

from __future__ import annotations

import json as _json

_HTML = r"""<!doctype html><html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>JARVIS</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="JARVIS">
<style>
:root{--bg:#05070d;--panel:#0b1120;--card:#0d1220;--border:#16233a;--cyan:#34e3f0;
--gold:#ffb84d;--mystic:#b47cff;--text:#cfe6ef;--dim:#7f97a6;--good:#3ff5b0;--bad:#ff5c72}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:"Rajdhani","Segoe UI",system-ui,sans-serif;
font-size:15px;padding:0 0 96px;min-height:100vh}
header{position:sticky;top:0;z-index:10;background:linear-gradient(#05070d,#05070dee);
border-bottom:1px solid var(--border);padding:12px 14px;display:flex;align-items:center;gap:10px}
.logo{font-family:"JetBrains Mono",monospace;font-weight:700;letter-spacing:4px;color:var(--cyan);font-size:15px}
.pill{margin-left:auto;font-family:monospace;font-size:11px;letter-spacing:1px;padding:3px 9px;
border:1px solid var(--border);border-radius:10px;color:var(--dim)}
.wrap{padding:14px;display:flex;flex-direction:column;gap:14px;max-width:640px;margin:0 auto}
.sec{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:12px}
.sec h2{font-family:monospace;font-size:10px;letter-spacing:2px;color:var(--cyan);margin-bottom:8px;font-weight:700}
#log{display:flex;flex-direction:column;gap:8px;max-height:44vh;overflow-y:auto}
.msg{padding:8px 11px;border-radius:11px;border:1px solid var(--border);background:var(--card);line-height:1.35}
.msg .who{font-family:monospace;font-size:9px;letter-spacing:2px;font-weight:700;margin-bottom:3px}
.msg.user{align-self:flex-end;max-width:85%}.msg.user .who{color:#82b1ff}
.msg.jarvis{align-self:flex-start;max-width:92%}.msg.jarvis .who{color:var(--gold)}
.msg.sys{align-self:center;font-size:12px;color:var(--dim);border-style:dashed}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.agent{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:8px;font-size:12px}
.agent .n{font-weight:700}.agent .d{color:var(--dim);font-size:10px;font-family:monospace}
.agent.act{border-color:var(--cyan);box-shadow:0 0 14px #34e3f033}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--dim);margin-right:5px}
.dot.on{background:var(--good)}.dot.warn{background:var(--gold)}.dot.err{background:var(--bad)}
.rem{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px}
.rem:last-child{border:0}.rem .t{color:var(--gold);font-family:monospace;font-size:11px}
.quick{display:flex;flex-wrap:wrap;gap:7px}
.quick button,.tog{background:var(--card);border:1px solid var(--border);color:var(--text);
border-radius:9px;padding:8px 12px;font-size:12px;font-family:monospace;letter-spacing:1px}
.togs{display:flex;flex-wrap:wrap;gap:8px}
.tog{display:flex;align-items:center;gap:7px}
.tog.on{border-color:var(--cyan);color:var(--cyan);background:#34e3f012}
.tog.call.on{border-color:var(--good);color:var(--good);background:#3ff5b012}
.tog.away.on{border-color:var(--gold);color:var(--gold);background:#ffb84d12}
.confirm-card{background:#1a0e14;border:1px solid var(--bad);border-radius:11px;padding:10px;margin-bottom:8px}
.confirm-card .cp{font-size:13px;line-height:1.4;margin-bottom:8px}
.confirm-card .cbtns{display:flex;gap:8px}
.confirm-card button{flex:1;border-radius:9px;padding:9px;font-size:12px;font-family:monospace;
letter-spacing:1px;border:1px solid var(--border)}
.confirm-card button.cok{background:#3ff5b022;border-color:var(--good);color:var(--good)}
.confirm-card button.cno{background:#ff5c7222;border-color:var(--bad);color:var(--bad)}
.bar{position:fixed;bottom:0;left:0;right:0;background:#05070d;border-top:1px solid var(--border);
padding:10px 12px;display:flex;gap:8px;align-items:center;max-width:640px;margin:0 auto}
#inp{flex:1;background:var(--card);border:1px solid var(--border);color:var(--text);
border-radius:11px;padding:11px 13px;font-size:15px}
#inp:focus{outline:none;border-color:var(--cyan)}
.icon{width:44px;height:44px;flex:none;border-radius:11px;border:1px solid var(--border);
background:var(--card);color:var(--cyan);font-size:19px;display:flex;align-items:center;justify-content:center}
.icon.rec{background:#ff5c7222;border-color:var(--bad);color:var(--bad);animation:pulse 1s infinite}
.icon.call{background:#3ff5b022;border-color:var(--good);color:var(--good)}
@keyframes pulse{50%{opacity:.5}}
.empty{color:var(--dim);font-size:12px}
.lib-tools{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.lib-tools input{flex:1;min-width:120px;background:var(--card);border:1px solid var(--border);color:var(--text);
  border-radius:8px;padding:7px 9px;font:inherit}
.book{border:1px solid var(--border);border-radius:10px;padding:8px 10px;margin:6px 0;background:var(--card)}
.book .h{display:flex;gap:8px;align-items:center;cursor:pointer}
.book .h img{width:30px;height:44px;object-fit:cover;border-radius:3px;background:#0003}
.book .t{font-weight:600}.book .a{color:var(--dim);font-size:12px}
.book .st{margin-left:auto;font-size:11px;color:var(--dim);white-space:nowrap}
.book .ed{margin-top:8px;display:grid;gap:6px}
.book .ed .row{display:flex;gap:6px;flex-wrap:wrap}
.book .ed input,.book .ed select,.book .ed textarea{background:#0006;border:1px solid var(--border);color:var(--text);
  border-radius:7px;padding:6px 8px;font:inherit;flex:1;min-width:90px}
.book .ed button,.lib-tools button{background:var(--card);border:1px solid var(--border);color:var(--text);
  border-radius:8px;padding:6px 10px;font:inherit;cursor:pointer}
.book .note{font-size:12px;color:var(--text);opacity:.85;padding:3px 0;border-top:1px dashed var(--border)}
.book .note b{color:var(--dim);cursor:pointer;margin-left:6px}
</style></head><body>
<header><span class="logo">J A R V I S</span><span class="pill" id="conn">baglaniyor</span><a class="pill" style="margin-left:0;text-decoration:none;color:var(--cyan)" href="/ekip" onclick="location.href='/ekip?key='+encodeURIComponent(KEY);return false;">EKiP</a><a class="pill" style="margin-left:0;text-decoration:none;color:var(--cyan)" href="/el" onclick="location.href='/el?key='+encodeURIComponent(KEY);return false;" title="El Kontrolu (kamera + jestler)">&#9995; EL</a></header>
<div class="wrap">
  <div class="sec" id="confirmSec" style="display:none;border-color:var(--bad)">
    <h2 style="color:var(--bad)">ONAY BEKLIYOR</h2><div id="confirms"></div></div>
  <div class="sec"><h2>GORUSME</h2><div class="togs">
    <button class="tog call" id="tCall">&#128222; Telefon gorusmesi</button>
    <button class="tog on" id="tTts">&#128266; Sesli yanit</button>
    <button class="tog away" id="tAway">&#128246; Uzak mod (PC sessiz)</button>
    <button class="tog" id="tWake">&#128066; Hey JARVIS (PC uyandirma)</button>
    <button class="tog" id="install" style="display:none">&#11015; Uygulamayi yukle</button>
  </div><div class="empty" id="callHint" style="margin-top:8px">Telefon gorusmesini ac: mikrofon surekli dinler, JARVIS telefonda sesli yanit verir.</div></div>
  <div class="sec"><h2>KONUSMA</h2><div id="log"><div class="empty">Henuz mesaj yok. Asagidan yaz veya mikrofona bas.</div></div></div>
  <div class="sec"><h2>HIZLI</h2><div class="quick" id="quick"></div></div>
  <div class="sec"><h2>KITAPLIK</h2>
    <div class="lib-tools">
      <input id="libQ" placeholder="Ara..." autocomplete="off">
      <button id="libPhoto">&#128247; Raf fotografindan ekle</button>
      <button id="libCal">&#128218; Calibre</button>
      <input type="file" id="libFile" accept="image/*" multiple style="display:none">
      <input type="file" id="libCover" accept="image/*" style="display:none">
    </div>
    <div class="lib-tools"><input id="libAd" placeholder="Kitap adi"><input id="libYazar" placeholder="Yazar">
      <button id="libAdd">Ekle</button></div>
    <div class="empty" id="libInfo"></div>
    <div id="lib"><div class="empty">yukleniyor...</div></div></div>
  <div class="sec"><h2>HATIRLATICILAR</h2><div id="rems"><div class="empty">yok</div></div></div>
  <div class="sec"><h2>DEPARTMAN & AJANLAR</h2><div class="grid" id="agents"><div class="empty">yukleniyor...</div></div></div>
</div>
<div class="bar">
  <input id="inp" placeholder="JARVIS'e yaz..." autocomplete="off">
  <button class="icon" id="mic" title="Sesli komut">&#127908;</button>
  <button class="icon" id="send" title="Gonder">&#10148;</button>
</div>
<script>
// key: adres cubugundan (?key=) VEYA daha once kaydedilmis olandan
let KEY=new URLSearchParams(location.search).get('key')||'';
try{ if(KEY) localStorage.setItem('jv_key',KEY); else KEY=localStorage.getItem('jv_key')||''; }catch(e){}
const q=s=>document.querySelector(s), esc=t=>(t||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{});}
let deferredPrompt=null;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();deferredPrompt=e;
  const b=document.getElementById('install');if(b)b.style.display='';});
window.addEventListener('appinstalled',()=>{const b=document.getElementById('install');if(b)b.style.display='none';});
function api(path,body){return fetch(path+(path.includes('?')?'&':'?')+'key='+encodeURIComponent(KEY),
  body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}).then(r=>r.json());}
function addMsg(who,text,cls){const l=q('#log');if(l.querySelector('.empty'))l.innerHTML='';
  const d=document.createElement('div');d.className='msg '+cls;
  d.innerHTML='<div class="who">'+who+'</div>'+esc(text);l.appendChild(d);l.scrollTop=l.scrollHeight;}

// ================= durum =================
let ttsOn=true, callMode=false, awayOn=false, wakeOn=false, speaking=false, recognizing=false;
let lastSpoken='', seenTs=0, confirmations=[];

// ================= onay (uzaktan/headless calisirken hassas araclar icin) =================
function renderConfirms(){
  const box=q('#confirms'), sec=q('#confirmSec');
  if(!confirmations.length){sec.style.display='none';box.innerHTML='';return;}
  sec.style.display='';box.innerHTML='';
  for(const c of confirmations){
    const d=document.createElement('div');d.className='confirm-card';
    d.innerHTML='<div class="cp">'+esc(c.prompt)+'</div><div class="cbtns">'+
      '<button class="cok" data-id="'+esc(c.id)+'">Onayla</button>'+
      '<button class="cno" data-id="'+esc(c.id)+'">Reddet</button></div>';
    box.appendChild(d);
  }
  box.querySelectorAll('.cok').forEach(b=>b.onclick=()=>resolveConfirm(b.dataset.id,true));
  box.querySelectorAll('.cno').forEach(b=>b.onclick=()=>resolveConfirm(b.dataset.id,false));
}
function resolveConfirm(id,approve){
  confirmations=confirmations.filter(c=>c.id!==id);renderConfirms();
  api('/api/confirm',{id,approve}).catch(()=>addMsg('SISTEM','onay gonderilemedi','sys'));
}

function renderState(s){
  q('#conn').textContent=(s.connection||'')+(s.engine_state?' · '+s.engine_state:'')+(s.away?' · UZAK':'');
  confirmations=s.confirmations||[];renderConfirms();
  const log=q('#log');
  if(s.transcript&&s.transcript.length){log.innerHTML='';for(const m of s.transcript){
    addMsg(m.who==='user'?'SEN':(m.who==='sys'?'SISTEM':'JARVIS'),m.text,
      m.who==='user'?'user':(m.who==='sys'?'sys':'jarvis'));}}
  if(typeof s.away==='boolean'&&s.away!==awayOn){awayOn=s.away;q('#tAway').classList.toggle('on',awayOn);}
  if(typeof s.wake==='boolean'){wakeOn=s.wake;q('#tWake').classList.toggle('on',wakeOn);}
  const ag=q('#agents');const names=Object.values(s.agents||{});
  ag.innerHTML=names.length?'':'<div class="empty">ajan yok</div>';
  for(const a of names){const st=a.status||'';const cls=(['running','routing','tool','queued'].includes(st))?'act':'';
    const dc=st==='done'?'on':(st==='failed'||st==='blocked'?'err':(st==='awaiting_approval'?'warn':''));
    const d=document.createElement('div');d.className='agent '+cls;
    d.innerHTML='<div class="n"><span class="dot '+dc+'"></span>'+esc(a.title||a.name)+'</div>'+
      '<div class="d">'+esc(a.department_title||a.department||'')+' · '+esc((a.autonomy||'').replace('_',' '))+(st?' · '+st:'')+'</div>';
    ag.appendChild(d);}
  const rl=q('#rems');rl.innerHTML=(s.reminders&&s.reminders.length)?'':'<div class="empty">yok</div>';
  for(const r of (s.reminders||[])){const d=document.createElement('div');d.className='rem';
    d.innerHTML='<span>'+esc(r.text)+'</span><span class="t">'+esc(r.fire_at_h||r.fire_at||'')+'</span>';rl.appendChild(d);}
}
const QUICK=[['Mailleri ozetle','gelen kutusundaki okunmamis mailleri ozetle'],
 ['Hava durumu','bulundugum sehrin hava durumunu soyle'],
 ['Ekrani oku','ekrandaki metni oku ve ozetle'],
 ['Sistem durumu','sistem durumunu soyle'],
 ['Bugun ne var','bugun icin bekleyen hatirlaticilari ve rutinleri soyle']];
const qd=q('#quick');QUICK.forEach(([lbl,cmd])=>{const b=document.createElement('button');
  b.textContent=lbl;b.onclick=()=>say(cmd);qd.appendChild(b);});

function say(text){text=(text||'').trim();if(!text)return;
  // eko: JARVIS'in az once soyledigi cumleyi geri gondermeyelim
  if(callMode&&lastSpoken&&similar(text,lastSpoken)){return;}
  addMsg('SEN',text,'user');
  api('/api/say',{text}).catch(()=>addMsg('SISTEM','gonderilemedi','sys'));q('#inp').value='';}
q('#send').onclick=()=>say(q('#inp').value);
q('#inp').addEventListener('keydown',e=>{if(e.key==='Enter')say(q('#inp').value);});

function similar(a,b){a=a.toLowerCase().replace(/[^\wçğışöü ]/g,'');b=b.toLowerCase().replace(/[^\wçğışöü ]/g,'');
  if(!a||!b)return false;const sh=a.length<b.length?a:b,lo=a.length<b.length?b:a;return lo.includes(sh)&&sh.length>8;}

// ================= TTS (telefonda sesli yanit) =================
let ttsVoice=null;
function pickVoice(){const vs=speechSynthesis.getVoices();
  ttsVoice=vs.find(v=>v.lang==='tr-TR')||vs.find(v=>v.lang&&v.lang.startsWith('tr'))||null;}
if('speechSynthesis' in window){pickVoice();speechSynthesis.onvoiceschanged=pickVoice;}
function speak(text){
  if(!ttsOn||!('speechSynthesis' in window)||!text)return;
  try{
    const u=new SpeechSynthesisUtterance(text);
    u.lang='tr-TR';if(ttsVoice)u.voice=ttsVoice;u.rate=1.05;u.pitch=1.0;
    u.onstart=()=>{speaking=true;lastSpoken=text;stopRec();};
    u.onend=u.onerror=()=>{speaking=false;setTimeout(()=>{if(callMode)startRec();},350);};
    speechSynthesis.cancel();speechSynthesis.speak(u);
  }catch(x){}
}

// ================= SSE canli akis =================
function connectSSE(){const ev=new EventSource('/api/events?key='+encodeURIComponent(KEY));
  ev.onmessage=e=>{try{const evt=JSON.parse(e.data);
    if(evt.kind==='kitaplik.degisti'){libLoad();}
    if(evt.kind==='transcript'){
      const m=evt.data;
      addMsg(m.who==='user'?'SEN':(m.who==='sys'?'SISTEM':'JARVIS'),m.text,
        m.who==='user'?'user':(m.who==='sys'?'sys':'jarvis'));
      if(m.who==='jarvis')speak(m.text);
    }
    else if(evt.kind==='snapshot'){renderState(evt.data);}
    else if(evt.kind==='connection'){q('#conn').textContent=evt.data;}
    else if(evt.kind==='control_state'){if(typeof evt.data.away==='boolean'){
      awayOn=evt.data.away;q('#tAway').classList.toggle('on',awayOn);}
      if(typeof evt.data.wake==='boolean'){wakeOn=evt.data.wake;q('#tWake').classList.toggle('on',wakeOn);}}
    else if(evt.kind==='confirmation_request'){
      if(!confirmations.find(c=>c.id===evt.data.id)){confirmations.push(evt.data);renderConfirms();}}
    else if(evt.kind==='confirmation_resolved'){
      confirmations=confirmations.filter(c=>c.id!==evt.data.id);renderConfirms();}
  }catch(x){}};
  ev.onerror=()=>{ev.close();setTimeout(connectSSE,3000);};}

// ================= tarayici sesli komut (Web Speech API) =================
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;let rec=null;
if(SR){
  rec=new SR();rec.lang='tr-TR';rec.interimResults=false;rec.continuous=false;
  rec.onresult=e=>{const t=e.results[e.results.length-1][0].transcript;q('#inp').value=t;say(t);};
  rec.onend=()=>{recognizing=false;q('#mic').classList.remove('rec');
    if(callMode&&!speaking){setTimeout(startRec,400);}};
  rec.onerror=ev=>{recognizing=false;q('#mic').classList.remove('rec');
    if(ev.error==='not-allowed'||ev.error==='service-not-allowed'){
      callMode=false;q('#tCall').classList.remove('on');q('#mic').classList.remove('call');
      addMsg('SISTEM','Mikrofon izni yok. Tarayici ayarlarindan izin verin.','sys');}};
  q('#mic').onclick=()=>{if(callMode)return;if(recognizing){stopRec();return;}startRec();};
}else{q('#mic').onclick=()=>alert('Bu tarayici sesli girisi desteklemiyor. Android Chrome onerilir.');}

function startRec(){if(!rec||recognizing||speaking)return;
  try{rec.start();recognizing=true;q('#mic').classList.add('rec');}catch(x){}}
function stopRec(){if(!rec||!recognizing)return;try{rec.stop();}catch(x){}}

// ================= toggle'lar =================
let wakeLock=null;
async function keepAwake(on){try{
  if(on&&'wakeLock' in navigator){wakeLock=await navigator.wakeLock.request('screen');}
  else if(!on&&wakeLock){wakeLock.release();wakeLock=null;}
}catch(x){}}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&callMode)keepAwake(true);});

q('#tCall').onclick=()=>{
  callMode=!callMode;
  q('#tCall').classList.toggle('on',callMode);
  q('#mic').classList.toggle('call',callMode);
  q('#callHint').textContent=callMode
    ?'Gorusme ACIK. Konusun; JARVIS telefonda sesli yanit verir. Kapatmak icin tekrar dokunun.'
    :'Telefon gorusmesini ac: mikrofon surekli dinler, JARVIS telefonda sesli yanit verir.';
  keepAwake(callMode);
  if(callMode){ if('speechSynthesis' in window){speechSynthesis.resume();} startRec(); }
  else{ stopRec(); }
};
q('#tTts').onclick=()=>{ttsOn=!ttsOn;q('#tTts').classList.toggle('on',ttsOn);
  if(!ttsOn&&'speechSynthesis' in window)speechSynthesis.cancel();};
q('#install').onclick=async()=>{if(!deferredPrompt){alert('Tarayici menusunden "Ana ekrana ekle" ile yukleyin.');return;}
  deferredPrompt.prompt();await deferredPrompt.userChoice;deferredPrompt=null;q('#install').style.display='none';};
q('#tAway').onclick=()=>{
  const next=!awayOn;
  api('/api/control',{action:next?'away_on':'away_off'})
    .then(r=>{awayOn=(r&&typeof r.away==='boolean')?r.away:next;
      q('#tAway').classList.toggle('on',awayOn);
      addMsg('SISTEM',awayOn?'Uzak mod acik - PC mikrofon ve hoparlor kapali.':'Uzak mod kapali - PC sesi acildi.','sys');})
    .catch(()=>addMsg('SISTEM','uzak mod degistirilemedi','sys'));
};

q('#tWake').onclick=()=>{
  const next=!wakeOn;
  api('/api/control',{action:next?'wake_on':'wake_off'})
    .then(r=>{if(r&&r.error)throw 0;wakeOn=next;q('#tWake').classList.toggle('on',wakeOn);
      addMsg('SISTEM',wakeOn?'Uyandirma kelimesi acik - PC yalnizca "Hey JARVIS" deyince dinler.':'Uyandirma kelimesi kapali - PC surekli dinler.','sys');})
    .catch(()=>addMsg('SISTEM','uyandirma kelimesi degistirilemedi','sys'));
};


// ================= KITAPLIK =================
let LIB=[], libOpen=null, coverFor=null;
const DUR={okunacak:'Okunacak',okunuyor:'Okunuyor',bitti:'Bitti'};
function libLoad(){api('/api/kitaplik').then(s=>{LIB=(s&&s.books)||[];libRender();}).catch(()=>{});}
function libRender(){
  const el=q('#lib'),f=(q('#libQ').value||'').toLocaleLowerCase('tr-TR');
  const named=LIB.filter(b=>b.ad).sort((a,b)=>(a.ad||'').localeCompare(b.ad||'','tr'));
  const list=named.filter(b=>!f||(b.ad+' '+(b.yazar||'')).toLocaleLowerCase('tr-TR').includes(f));
  const unnamed=LIB.length-named.length;
  q('#libInfo').textContent=named.length+' kitap'+(unnamed?' · '+unnamed+' adsiz raf kutusu (El Kontrolu > K)':'');
  el.innerHTML=list.length?'':'<div class="empty">kitap yok - ekleyin ya da raf fotografi yukleyin</div>';
  for(const b of list.slice(0,200)){
    const d=document.createElement('div');d.className='book';
    const cov=b.kapak?'<img src="/api/kitaplik/kapak/'+encodeURIComponent(b.id)+'?key='+encodeURIComponent(KEY)+'&v='+encodeURIComponent(b.kapak)+'">':'<img>';
    d.innerHTML='<div class="h">'+cov+'<div><div class="t">'+esc(b.ad)+'</div><div class="a">'+esc(b.yazar||'')+
      ((b.calibre&&b.calibre.formatlar&&b.calibre.formatlar.length)?' · e-kitap':'')+'</div></div><span class="st">'+
      esc(DUR[b.durum]||'')+(b.sayfa?' · s.'+b.sayfa:'')+(b.notlar&&b.notlar.length?' · '+b.notlar.length+' not':'')+'</span></div>';
    d.querySelector('.h').onclick=()=>{libOpen=libOpen===b.id?null:b.id;libRender();};
    if(libOpen===b.id)d.appendChild(libEditor(b));
    el.appendChild(d);}
}
function libEditor(b){
  const e=document.createElement('div');e.className='ed';
  const dfl=b.defter;
  e.innerHTML='<div class="row"><select class="du">'+Object.keys(DUR).map(k=>'<option value="'+k+'"'+(b.durum===k?' selected':'')+'>'+DUR[k]+'</option>').join('')+
    '</select><input class="sa" type="number" min="0" placeholder="Sayfa" value="'+(b.sayfa||'')+'"><button class="sv">Kaydet</button></div>'+
    '<div class="row"><input class="nt" placeholder="Not ya da alinti..."><button class="an">+ Not</button><button class="aq">+ Alinti</button></div>'+
    '<div class="row"><button class="jd">'+(dfl?'Jarvis yeniden yazsin':'Jarvis doldursun')+'</button><button class="cv">Kapak yukle</button><button class="rm">Sil</button></div>'+
    '<div class="empty dz">'+(dfl?(dfl.bilinmiyor?'Jarvis bu kitabi tanimiyor.':esc(dfl.ozet||'')):'Henuz Jarvis ozeti yok.')+'</div>';
  const notes=[...(b.notlar||[]).map((n,i)=>['not',i,n.metin]),...(b.alintilar||[]).map((n,i)=>['alinti',i,'“'+n.metin+'”'])];
  for(const [tur,i,m] of notes){const n=document.createElement('div');n.className='note';n.innerHTML=esc(m)+'<b title="sil">&#10005;</b>';
    n.querySelector('b').onclick=()=>libOp({islem:'not_sil',id:b.id,tur,index:i});e.appendChild(n);}
  e.querySelector('.sv').onclick=()=>libOp({islem:'guncelle',id:b.id,durum:e.querySelector('.du').value,sayfa:e.querySelector('.sa').value});
  const addNote=tur=>{const v=e.querySelector('.nt').value.trim();if(v)libOp({islem:tur,id:b.id,metin:v});};
  e.querySelector('.an').onclick=()=>addNote('not');e.querySelector('.aq').onclick=()=>addNote('alinti');
  e.querySelector('.jd').onclick=()=>{e.querySelector('.dz').textContent='Jarvis yaziyor...';
    api('/api/kitaplik/defter',{id:b.id,force:!!dfl}).then(r=>{if(r.error)throw r.error;libLoad();}).catch(x=>{e.querySelector('.dz').textContent='Yazilamadi: '+x;});};
  e.querySelector('.cv').onclick=()=>{coverFor=b.id;q('#libCover').click();};
  e.querySelector('.rm').onclick=()=>{if(confirm(b.ad+' silinsin mi?'))libOp({islem:'sil',id:b.id});};
  return e;
}
function libOp(body){return api('/api/kitaplik/kitap',body).then(r=>{if(r.error)addMsg('SISTEM',r.error,'sys');libLoad();});}
function rawPost(path,file){return fetch(path+(path.includes('?')?'&':'?')+'key='+encodeURIComponent(KEY),
  {method:'POST',headers:{'Content-Type':file.type||'image/jpeg'},body:file}).then(r=>r.json());}
// telefon fotografi buyuk olabilir: 2400 px'e kucult
function shrink(file){return new Promise(res=>{const img=new Image();img.onload=()=>{const s=Math.min(1,2400/Math.max(img.width,img.height));
  if(s>=1&&file.size<6e6){res(file);return;}const c=document.createElement('canvas');c.width=img.width*s;c.height=img.height*s;
  c.getContext('2d').drawImage(img,0,0,c.width,c.height);c.toBlob(b=>res(b||file),'image/jpeg',0.9);};img.onerror=()=>res(file);
  img.src=URL.createObjectURL(file);});}
q('#libQ').addEventListener('input',libRender);
q('#libAdd').onclick=()=>{const ad=q('#libAd').value.trim();if(!ad)return;
  libOp({islem:'ekle',ad,yazar:q('#libYazar').value.trim()}).then(()=>{q('#libAd').value='';q('#libYazar').value='';});};
q('#libPhoto').onclick=()=>q('#libFile').click();
q('#libFile').onchange=async e=>{const files=[...e.target.files];e.target.value='';
  for(const [i,f] of files.entries()){q('#libInfo').textContent='Fotograf okunuyor '+(i+1)+'/'+files.length+'...';
    try{const r=await rawPost('/api/kitaplik/foto',await shrink(f));
      addMsg('SISTEM',r.error?('Fotograf: '+r.error):('Fotograftan '+r.okunan+' kitap okundu, '+r.eklenen.length+' yeni eklendi'+(r.zaten_vardi.length?' ('+r.zaten_vardi.length+' zaten vardi)':'')),'sys');}
    catch(x){addMsg('SISTEM','fotograf gonderilemedi','sys');}}
  libLoad();};
q('#libCover').onchange=async e=>{const f=e.target.files[0];e.target.value='';if(!f||!coverFor)return;
  const r=await rawPost('/api/kitaplik/kapak?id='+encodeURIComponent(coverFor),await shrink(f)).catch(()=>({error:'gonderilemedi'}));
  if(r.error)addMsg('SISTEM','Kapak: '+r.error,'sys');libLoad();};
q('#libCal').onclick=()=>{q('#libInfo').textContent='Calibre esitleniyor...';
  api('/api/kitaplik/calibre',{}).then(r=>{addMsg('SISTEM',r.error?r.error:('Calibre: '+r.toplam+' e-kitap, '+r.eklenen+' yeni'),'sys');libLoad();});};
libLoad();
api('/api/state').then(renderState).catch(()=>{});
setInterval(()=>api('/api/state').then(renderState).catch(()=>{}),8000);
connectSSE();
</script></body></html>"""


def render_page() -> str:
    return _HTML


# --------------------------------------------------------------------- PWA


def render_manifest(token: str = "") -> str:
    """Web App Manifest. `token` verilirse start_url'e gomulur (tek dokunusla acilir)."""
    start = f"/?key={token}&pwa=1" if token else "/?pwa=1"
    return _json.dumps(
        {
            "name": "JARVIS",
            "short_name": "JARVIS",
            "description": "JARVIS sesli asistan - telefon konsolu",
            "lang": "tr",
            "start_url": start,
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#05070d",
            "theme_color": "#05070d",
            "categories": ["productivity", "utilities"],
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        },
        ensure_ascii=False,
        indent=1,
    )


PWA_SERVICE_WORKER = r"""
const C = 'jarvis-shell-v1';
const SHELL = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).catch(() => {}));
});
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // API ve canli akis: her zaman ag, cache yok
  if (url.pathname.startsWith('/api/')) return;
  // Gezinme: ag-once, cevrimdisi ise kabuk
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/')));
    return;
  }
  // Statik kabuk: cache-once
  if (SHELL.includes(url.pathname) || url.pathname.startsWith('/icon-')) {
    e.respondWith(
      caches.match(e.request).then(r => r || fetch(e.request).then(resp => {
        const clone = resp.clone();
        caches.open(C).then(c => c.put(e.request, clone));
        return resp;
      }))
    );
  }
});
"""
