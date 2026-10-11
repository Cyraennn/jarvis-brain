"""Stark Ekibi sayfasi (/ekip) - her yapay zeka persona'siyla yazili ve sesli konusma.

Iki mod:
  - SOHBET: kart sec -> yaz/konus -> persona kendi modeliyle ve kendi sesiyle yanitlar.
    Ekip koprusu acikken persona once bir ekip arkadasina danisabilir; danisma zinciri
    (soru + arkadasin sesli yaniti) da gosterilir ve sirayla seslendirilir.
  - TOPLANTI: birden cok uye sec -> soru sor -> uyeler sirayla, birbirinin soylediklerini
    gorerek konusur; en sonda secilen uye toplantiyi ozetler.
J.A.R.V.I.S. canli beyne gider ve PC'den kendi Live sesiyle konusur (toplantiya katilamaz).
"""

from __future__ import annotations

_HTML = r"""<!doctype html><html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>Stark Ekibi</title>
<link rel="icon" href="/favicon.ico">
<style>
:root{--bg:#05070d;--panel:#0b1120;--card:#0d1220;--border:#16233a;--cyan:#34e3f0;
--gold:#ffb84d;--text:#cfe6ef;--dim:#7f97a6;--good:#3ff5b0;--bad:#ff5c72}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:"Rajdhani","Segoe UI",system-ui,sans-serif;
font-size:15px;min-height:100vh;padding-bottom:84px;overflow-x:hidden}
header{position:sticky;top:0;z-index:10;background:linear-gradient(#05070d,#05070dee);
border-bottom:1px solid var(--border);padding:12px 16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.logo{font-family:"JetBrains Mono",monospace;font-weight:700;letter-spacing:4px;color:var(--cyan);font-size:15px}
header a{color:var(--dim);font-family:monospace;font-size:11px;letter-spacing:1px;text-decoration:none;
border:1px solid var(--border);border-radius:10px;padding:3px 9px}
.tabs{display:flex;gap:6px;margin-left:auto}
.tog,.tab{background:var(--card);border:1px solid var(--border);color:var(--dim);
border-radius:10px;padding:4px 10px;font-family:monospace;font-size:11px;letter-spacing:1px;cursor:pointer}
.tog.on,.tab.on{color:var(--cyan);border-color:var(--cyan)}
.tog.paid.on{color:var(--bad);border-color:var(--bad)}
.wrap{max-width:980px;margin:0 auto;padding:14px 16px;display:flex;flex-direction:column;gap:12px}
.opts{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--dim)}
.opts select{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;
padding:4px 6px;font-family:monospace;font-size:11px}
.hint{font-size:12px;color:var(--dim)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.card{position:relative;background:var(--card);border:1px solid var(--border);border-radius:12px;
padding:10px 11px;cursor:pointer;transition:border-color .2s,box-shadow .2s,opacity .2s;min-width:0}
.card:hover{border-color:var(--c)}
.card.sel{border-color:var(--c);box-shadow:0 0 16px color-mix(in srgb,var(--c) 30%,transparent)}
.card.off{opacity:.35;cursor:not-allowed}
.card .n{font-family:"JetBrains Mono",monospace;font-weight:700;letter-spacing:1px;color:var(--c);font-size:14px}
.card .m{font-family:monospace;font-size:10px;color:var(--dim);margin:3px 0 5px;overflow-wrap:anywhere}
.card .r{font-size:12px;line-height:1.3}
.card .seat{position:absolute;bottom:8px;right:10px;font-family:monospace;font-size:10px;color:var(--c)}
.badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.b{font-family:monospace;font-size:9px;letter-spacing:1px;padding:1px 6px;border-radius:8px;
border:1px solid var(--border);color:var(--dim)}
.b.paid{color:var(--bad);border-color:var(--bad)}
.orb{position:absolute;top:10px;right:10px;width:9px;height:9px;border-radius:50%;background:var(--c);opacity:.35}
.card.talk .orb{opacity:1;animation:pulse .8s ease-in-out infinite}
.card.think .orb{opacity:1;animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 var(--c)}50%{box-shadow:0 0 0 7px transparent}}
.chat{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:12px;min-width:0}
.chat h2{font-family:monospace;font-size:11px;letter-spacing:2px;margin-bottom:8px;color:var(--c,var(--cyan))}
#log{display:flex;flex-direction:column;gap:8px;max-height:48vh;overflow-y:auto}
.msg{padding:8px 11px;border-radius:11px;border:1px solid var(--border);background:var(--card);
line-height:1.4;max-width:92%;overflow-wrap:anywhere}
.msg .who{font-family:monospace;font-size:10px;letter-spacing:1px;font-weight:700;color:var(--c);margin-bottom:2px}
.msg.user{align-self:flex-end}.msg.ai{align-self:flex-start;border-left:3px solid var(--c)}
.msg.bridge{align-self:flex-start;margin-left:18px;max-width:86%;font-size:13px;border-style:dashed;border-left:3px solid var(--c)}
.msg.link{align-self:flex-start;margin-left:18px;font-family:monospace;font-size:11px;color:var(--dim);
border:0;background:none;padding:0 4px}
.msg.err{align-self:flex-start;border-color:var(--bad);color:var(--bad);font-size:13px}
.msg.sum{border-left-width:5px;box-shadow:0 0 14px color-mix(in srgb,var(--c) 18%,transparent)}
.msg .meta{font-family:monospace;font-size:9px;color:var(--dim);margin-top:4px;letter-spacing:1px}
.msg .src a{color:var(--cyan);font-size:11px;margin-right:8px}
.empty{color:var(--dim);font-size:13px}
.bar{position:fixed;left:0;right:0;bottom:0;background:#05070df2;border-top:1px solid var(--border);
padding:10px 16px calc(10px + env(safe-area-inset-bottom));display:flex;justify-content:center}
.bar .in{display:flex;gap:8px;width:100%;max-width:980px}
#inp{flex:1;min-width:0;background:var(--card);border:1px solid var(--border);border-radius:11px;
color:var(--text);padding:11px 12px;font-size:15px;font-family:inherit}
#inp:focus{outline:none;border-color:var(--cyan)}
.icon{flex:none;width:46px;height:44px;border-radius:11px;border:1px solid var(--border);
background:var(--card);color:var(--text);font-size:18px;cursor:pointer}
.icon.rec{border-color:var(--bad);color:var(--bad);animation:pulse 1s infinite;--c:var(--bad)}
</style></head><body>
<header><span class="logo">STARK EKiBi</span><a href="/">&larr; KONSOL</a>
<div class="tabs"><button class="tab on" id="tabChat">SOHBET</button><button class="tab" id="tabMeet">TOPLANTI</button>
<button class="tog on" id="tts" title="Yanitlari sesli oku">&#128266; SES</button></div></header>
<div class="wrap">
  <div class="opts" id="chatOpts">
    <button class="tog on" id="tConsult" title="Yapay zeka gerekirse ekip arkadasina danissin">&#128279; EKiP KOPRUSU</button>
    <button class="tog paid" id="tPaid" title="Ucretli V.E.R.O.N.I.C.A.'ya danisilabilsin">V.E.R.O.N.I.C.A. DANISILABiLiR</button>
  </div>
  <div class="opts" id="meetOpts" style="display:none">
    <span>Uyeleri sec (kartlara dokun) &middot; Tur:</span>
    <select id="rounds"><option value="1">1</option><option value="2">2</option></select>
    <span>Ozetleyen:</span><select id="summ"></select>
  </div>
  <div class="grid" id="grid"><div class="empty">yukleniyor...</div></div>
  <div class="chat" id="chat"><h2 id="title">BiR YAPAY ZEKA SEC</h2>
    <div id="log"><div class="empty">Yukaridan bir karta dokun, sonra yaz ya da mikrofona konus.</div></div></div>
</div>
<div class="bar"><div class="in">
  <input id="inp" placeholder="Bir yapay zeka sec..." autocomplete="off">
  <button class="icon" id="mic" title="Mikrofon">&#127908;</button>
  <button class="icon" id="stop" title="Durdur">&#9209;</button>
  <button class="icon" id="send" title="Gonder">&#10148;</button>
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

let personas=[],P={},sel=null,mode='chat';
let ttsOn=pref('team_tts',true),consultOn=pref('team_consult',true),paidOn=false;
let members=['pepper','homer','karen'],meetRun=0;
const logs={};  // 'chat:<key>' | 'meet' -> [{kind,persona,text,meta,sources}]
function bindTog(id,get,set){const b=q(id);b.classList.toggle('on',get());b.onclick=()=>{set(!get());b.classList.toggle('on',get());};}
bindTog('#tts',()=>ttsOn,v=>{ttsOn=v;setPref('team_tts',v);if(!v)stopAudio();});
bindTog('#tConsult',()=>consultOn,v=>{consultOn=v;setPref('team_consult',v);});
bindTog('#tPaid',()=>paidOn,v=>{paidOn=v;});

// ------------------------------------------------------------------ kartlar
function cardOf(k){return q('.card[data-k="'+k+'"]');}
function renderGrid(){
  q('#grid').innerHTML=personas.map(p=>`<div class="card" data-k="${esc(p.key)}" style="--c:${esc(p.color)}">
    <span class="orb"></span><div class="n">${esc(p.name)}</div><div class="m">${esc(p.model)}</div>
    <div class="r">${esc(p.role)}</div><div class="badges"><span class="b">${esc(p.provider.toUpperCase())}</span>
    ${p.provider==='live'?'<span class="b">CANLI SES</span>':''}${p.paid?'<span class="b paid">UCRETLI</span>':''}</div>
    <span class="seat"></span></div>`).join('');
  document.querySelectorAll('.card').forEach(c=>c.onclick=()=>mode==='chat'?select(c.dataset.k):toggleMember(c.dataset.k));
  refreshCards();
}
function refreshCards(){
  document.querySelectorAll('.card').forEach(c=>{
    const k=c.dataset.k,i=members.indexOf(k);
    if(mode==='chat'){c.classList.toggle('sel',!!sel&&sel.key===k);c.classList.remove('off');c.querySelector('.seat').textContent='';}
    else{c.classList.toggle('sel',i>=0);c.classList.toggle('off',P[k].provider==='live');
      c.querySelector('.seat').textContent=i>=0?('#'+(i+1)):'';}
  });
  if(mode==='meet'){
    const s=q('#summ'),cur=s.value;
    s.innerHTML=personas.filter(p=>p.provider!=='live').map(p=>`<option value="${esc(p.key)}">${esc(p.name)}${p.paid?' ($)':''}</option>`).join('');
    s.value=cur||'friday';
  }
}
function toggleMember(k){
  if(P[k].provider==='live')return;
  const i=members.indexOf(k); if(i>=0)members.splice(i,1); else members.push(k);
  refreshCards();renderLog();
}
function select(k){
  sel=P[k];if(!sel)return;
  q('#chat').style.setProperty('--c',sel.color);
  refreshCards();renderLog();q('#inp').focus();
}
function setMode(m){
  mode=m;q('#tabChat').classList.toggle('on',m==='chat');q('#tabMeet').classList.toggle('on',m==='meet');
  q('#chatOpts').style.display=m==='chat'?'':'none';q('#meetOpts').style.display=m==='meet'?'':'none';
  if(m==='meet')q('#chat').style.setProperty('--c','var(--gold)');else if(sel)q('#chat').style.setProperty('--c',sel.color);
  refreshCards();renderLog();
}
q('#tabChat').onclick=()=>setMode('chat');q('#tabMeet').onclick=()=>setMode('meet');

// ------------------------------------------------------------------ log
function logKey(){return mode==='meet'?'meet':(sel?'chat:'+sel.key:'');}
function renderLog(){
  const k=logKey();
  if(mode==='meet'){
    q('#title').textContent='EKiP TOPLANTISI · '+(members.map(m=>P[m]&&P[m].name).join(', ')||'uye sec');
    q('#inp').placeholder='Toplantiya bir soru sor...';
  }else if(sel){q('#title').textContent=sel.name+' · '+sel.model;q('#inp').placeholder=sel.name+"'a yaz...";}
  else{q('#title').textContent='BiR YAPAY ZEKA SEC';q('#inp').placeholder='Bir yapay zeka sec...';}
  const items=logs[k]||[];
  if(!items.length){q('#log').innerHTML='<div class="empty">'+(mode==='meet'
    ?'Kartlara dokunarak uyeleri sec, sonra soruyu yaz ya da mikrofona soyle. Uyeler sirayla, birbirini dinleyerek konusur.'
    :(sel?esc(sel.name)+' hazir. Yaz ya da mikrofona bas.':'Yukaridan bir karta dokun.'))+'</div>';return;}
  q('#log').innerHTML=items.map(m=>{
    const p=P[m.persona]||{},c=p.color||'var(--cyan)';
    if(m.kind==='err')return `<div class="msg err">${esc(m.text)}</div>`;
    if(m.kind==='user')return `<div class="msg user">${esc(m.text)}</div>`;
    if(m.kind==='link')return `<div class="msg link" style="--c:${esc(c)}">&#8627; ${esc(m.text)}</div>`;
    const src=(m.sources||[]).filter(s=>s.url).slice(0,4).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title||'kaynak')}</a>`).join('');
    const cls=m.kind==='bridge'?'bridge':('ai'+(m.kind==='sum'?' sum':''));
    return `<div class="msg ${cls}" style="--c:${esc(c)}"><div class="who">${esc(p.name||'')}${m.kind==='sum'?' · OZET':''}</div>${esc(m.text)}${src?'<div class="src">'+src+'</div>':''}${m.meta?'<div class="meta">'+esc(m.meta)+'</div>':''}</div>`;
  }).join('');
  q('#log').scrollTop=q('#log').scrollHeight;
}
function push(k,m){(logs[k]=logs[k]||[]).push(m);if(logKey()===k)renderLog();}

// ------------------------------------------------------------------ ses kuyrugu (sirayla)
let queue=[],playing=null,audio=null;
function talking(k,on){const c=cardOf(k);if(c)c.classList.toggle('talk',on);}
function stopAudio(){queue=[];if(audio){audio.pause();audio=null;}
  if('speechSynthesis' in window)speechSynthesis.cancel();
  document.querySelectorAll('.card.talk').forEach(c=>c.classList.remove('talk'));playing=null;}
function enqueue(key,text,dataUrl){if(!ttsOn||!text)return;queue.push({key,text,dataUrl});if(!playing)next();}
function next(){
  const it=queue.shift();playing=it||null;if(!it)return;
  const done=()=>{talking(it.key,false);audio=null;playing=null;next();};
  talking(it.key,true);
  if(it.dataUrl){audio=new Audio(it.dataUrl);audio.onended=audio.onerror=done;
    audio.play().catch(()=>{talking(it.key,false);browserSay(it,done);});}
  else browserSay(it,done);
}
function browserSay(it,done){
  if(!('speechSynthesis' in window)){done();return;}
  const u=new SpeechSynthesisUtterance(it.text);u.lang='tr-TR';
  const v=speechSynthesis.getVoices().find(v=>v.lang&&v.lang.startsWith('tr'));if(v)u.voice=v;
  let h=0;for(const ch of it.key)h=(h*31+ch.charCodeAt(0))%997;u.pitch=0.7+(h%7)*0.1;u.rate=1.05;
  u.onstart=()=>talking(it.key,true);u.onend=u.onerror=done;speechSynthesis.speak(u);
}

// ------------------------------------------------------------------ sohbet (+ ekip koprusu)
let waitingJarvis=false;
async function sendChat(text){
  if(!sel){alert('Once bir yapay zeka sec.');return;}
  const p=sel,k='chat:'+p.key;
  const history=(logs[k]||[]).filter(m=>m.kind==='user'||m.kind==='ai').slice(-8)
    .map(m=>({role:m.kind==='user'?'user':'assistant',text:m.text}));
  push(k,{kind:'user',text});
  const card=cardOf(p.key);card&&card.classList.add('think');
  try{
    const r=await api('/api/team/ask',{persona:p.key,text,history,consult:consultOn,allow_paid:paidOn});
    if(!r.ok){push(k,{kind:'err',text:(r.j&&r.j.error)||('hata '+r.status)});return;}
    const res=r.j;
    if(res.via==='live'){waitingJarvis=true;push(k,{kind:'ai',persona:'jarvis',text:'(PC hoparlorunden yanitliyor...)',meta:'canli oturum'});return;}
    for(const c of res.consults||[]){
      const to=P[c.to];
      push(k,{kind:'link',persona:c.to,text:p.name+' → '+(to?to.name:c.to)+': '+c.question});
      if(c.text){push(k,{kind:'bridge',persona:c.to,text:c.text,sources:c.sources,meta:c.model||''});enqueue(c.to,c.text,c.audio);}
      else push(k,{kind:'err',text:(to?to.name:c.to)+' danisilamadi: '+(c.error||'?')});
    }
    if(res.error&&!res.text){push(k,{kind:'err',text:p.name+' yanit vermedi: '+res.error});return;}
    push(k,{kind:'ai',persona:p.key,text:res.text,sources:res.sources,meta:(res.model||'')+(res.audio?' · ses':'')});
    enqueue(p.key,res.text,res.audio);
  }catch(e){push(k,{kind:'err',text:'baglanti hatasi: '+e});}
  finally{card&&card.classList.remove('think');}
}

// ------------------------------------------------------------------ toplanti masasi
async function sendMeet(topic){
  const seats=members.filter(m=>P[m]&&P[m].provider!=='live');
  if(seats.length<2){alert('Toplanti icin en az 2 uye sec.');return;}
  const summ=q('#summ').value,rounds=+q('#rounds').value,run=++meetRun;
  if(P[summ].paid&&!seats.includes(summ)&&!confirm('Ozetleyen V.E.R.O.N.I.C.A. ucretli. Devam?'))return;
  logs.meet=[];push('meet',{kind:'user',text:topic});
  const transcript=[];  // her uye kendinden oncekilerin soylediklerini gorur
  async function turn(key,final){
    if(run!==meetRun)return false;
    const card=cardOf(key);card&&card.classList.add('think');
    try{
      const r=await api('/api/team/council/turn',{persona:key,topic,transcript,final});
      if(run!==meetRun)return false;
      const res=r.j||{};
      if(!r.ok||!res.text){push('meet',{kind:'err',text:P[key].name+': '+(res.error||('hata '+r.status))});return true;}
      transcript.push({persona:key,text:res.text});
      push('meet',{kind:final?'sum':'ai',persona:key,text:res.text,sources:res.sources,meta:res.model||''});
      enqueue(key,res.text,res.audio);
    }catch(e){push('meet',{kind:'err',text:'baglanti hatasi: '+e});}
    finally{card&&card.classList.remove('think');}
    return true;
  }
  for(let r=0;r<rounds;r++)for(const key of seats){if(!(await turn(key,false)))return;}
  await turn(summ,true);
}

async function send(text){
  text=(text||'').trim();if(!text)return;q('#inp').value='';
  if(mode==='meet')return sendMeet(text);
  return sendChat(text);
}
q('#send').onclick=()=>send(q('#inp').value);
q('#inp').onkeydown=e=>{if(e.key==='Enter')send(q('#inp').value);};
q('#stop').onclick=()=>{meetRun++;stopAudio();};

// ------------------------------------------------------------------ mikrofon (Chrome/Edge)
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;let rec=null,recOn=false;
q('#mic').onclick=()=>{
  if(!SR){alert('Bu tarayici ses tanimayi desteklemiyor (Chrome/Edge kullan).');return;}
  if(recOn){rec&&rec.stop();return;}
  if(mode==='chat'&&!sel){alert('Once bir yapay zeka sec.');return;}
  stopAudio();
  rec=new SR();rec.lang='tr-TR';rec.interimResults=false;rec.continuous=false;
  rec.onresult=e=>{const t=e.results[0][0].transcript;q('#inp').value=t;send(t);};
  rec.onend=rec.onerror=()=>{recOn=false;q('#mic').classList.remove('rec');};
  recOn=true;q('#mic').classList.add('rec');rec.start();
};

// ------------------------------------------------------------------ J.A.R.V.I.S. (SSE)
function connectSSE(){const ev=new EventSource('/api/events?key='+encodeURIComponent(KEY));
  ev.onmessage=e=>{try{const evt=JSON.parse(e.data);
    if(evt.kind==='transcript'&&evt.data.who==='jarvis'&&waitingJarvis)
      push('chat:jarvis',{kind:'ai',persona:'jarvis',text:evt.data.text,meta:'gemini-2.5-flash-native-audio · canli ses'});
  }catch(x){}};
  ev.onerror=()=>{ev.close();setTimeout(connectSSE,3000);};}

api('/api/team').then(r=>{
  if(!r.ok){q('#grid').innerHTML='<div class="empty">Erisim yok ('+r.status+'). Adrese ?key=... ekle.</div>';return;}
  personas=r.j.personas||[];P=Object.fromEntries(personas.map(p=>[p.key,p]));
  if(!r.j.tts)q('#tts').title='Sunucu sesi kapali: tarayici sesi kullanilir';
  renderGrid();connectSSE();
});
if('speechSynthesis' in window)speechSynthesis.getVoices();
</script></body></html>"""


def render_team_page() -> str:
    return _HTML
