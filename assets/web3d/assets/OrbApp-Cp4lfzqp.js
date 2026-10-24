import{r as e,s as t,t as n}from"./index-Dwy9AKo7.js";import{Ct as r,a as i,h as a,i as o,n as s,s as c,t as l,x as u}from"./dist-wqgMUxrY.js";var d=t(e(),1),f=new URLSearchParams(window.location.search).get(`embedded`)===`1`,p={amp:0,thinking:!1,asleep:!1,introAt:performance.now(),persona:`jarvis`,equator:`#22e3ff`,pole:`#1e8fff`};function m(e){let t=document.documentElement;e.base&&t.style.setProperty(`--o`,e.base),e.accent&&(t.style.setProperty(`--accent`,e.accent),t.style.setProperty(`--hc-accent`,e.accent)),e.persona&&(p.persona=e.persona,t.dataset.persona=e.persona),e.equator&&(p.equator=e.equator),e.pole&&(p.pole=e.pole)}var h={state:`idle`,caption:``,status:`HAZIR`,active:!0,landed:!1},g=new Set,_={get:()=>h,set(e){h={...h,...e},g.forEach(e=>e())},subscribe(e){return g.add(e),()=>g.delete(e)}};function v(e){return(0,d.useSyncExternalStore)(_.subscribe,()=>e(h))}var y=0;function b(e){y+=1,document.title=`jarvis:${e}:${y}`}function x(){return window.jarvis={setVoice(e){typeof e.level==`number`&&(p.amp=Math.min(1,Math.max(0,e.level)*3.2)),typeof e.thinking==`boolean`&&(p.thinking=e.thinking),typeof e.asleep==`boolean`&&(p.asleep=e.asleep),e.state&&e.state!==h.state&&_.set({state:e.state})},setCaption:e=>_.set({caption:String(e??``)}),setStatus:e=>_.set({status:String(e??``)}),setActive:e=>_.set({active:!!e}),intro(){p.introAt=performance.now(),_.set({landed:!1})},setTheme:e=>m(e??{})},()=>void 0}var S=0;function C(){if(f||S)return;_.set({state:`speaking`,caption:`Emrinizdeyim efendim. Bugün takviminizde iki toplantı ve bir ödev teslimi var.`});let e=performance.now();S=window.setInterval(()=>{let t=(performance.now()-e)/1e3;p.amp=Math.max(0,.35+.3*Math.sin(t*9)*Math.sin(t*2.3)+(Math.random()-.5)*.25),t>4.5&&(window.clearInterval(S),S=0,p.amp=0,_.set({state:`idle`}))},40)}var w=n(),T=[[7,1],[9,0],[14,1],[17,0],[22,1],[26,0],[15,0],[19,1],[10,0],[16,1],[20,0],[24,1],[13,0],[18,1],[24,0],[14,1],[11,0],[8,1]].map(([e,t])=>({h:e,xtra:!!t})),E=[`Planla`,`Hatırla`,`Araştır`,`Yaz`,`Düzenle`,`Takip et`,`Otomatikleştir`,`Bağlan`,`Öğren`,`Koru`,`Sadeleştir`,`Yönet`];function D({driven:e}){let t=(0,d.useRef)([]);return(0,d.useEffect)(()=>{if(!e){t.current.forEach(e=>e&&(e.style.transform=``));return}let n=0,r=()=>{let e=p.amp;t.current.forEach((t,n)=>{t&&(t.style.transform=`scaleY(${.25+e*(.85+.4*Math.sin(n*2.1))})`)}),n=requestAnimationFrame(r)};return r(),()=>cancelAnimationFrame(n)},[e]),(0,w.jsx)(`span`,{className:`hc-wave`,"aria-hidden":`true`,children:T.map((e,n)=>(0,w.jsx)(`span`,{ref:e=>{t.current[n]=e},className:e.xtra?`xtra`:void 0,style:{"--h":`${e.h}px`,"--i":n}},n))})}function O(){let e=v(e=>e.state),t=v(e=>e.caption),n=v(e=>e.status),r=v(e=>e.landed),i=e===`speaking`||e===`listening`,a=()=>{f?b(`mic`):C()};return(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(`div`,{className:`corner-glow corner-glow-tl`}),(0,w.jsx)(`div`,{className:`corner-glow corner-glow-tr`}),(0,w.jsx)(`div`,{className:`ticker-wrap`,"aria-hidden":`true`,children:(0,w.jsx)(`div`,{className:`ticker-track`,children:[...E,...E].map((e,t)=>(0,w.jsx)(`span`,{children:e},t))})}),(0,w.jsxs)(`section`,{className:`hc-root`,"data-state":e,"data-driven":i,"data-landed":r,children:[(0,w.jsx)(`p`,{className:`hc-bubble`,"aria-live":`polite`,children:t}),(0,w.jsxs)(`div`,{className:`hc-hud`,children:[(0,w.jsxs)(`button`,{type:`button`,className:`hc-voice`,onClick:a,title:f?`Mikrofonu aç / kapat`:`Konuşma benzetimi`,children:[(0,w.jsx)(D,{driven:i}),(0,w.jsx)(`span`,{className:`hc-say-hi`,children:`“Hey JARVIS” de`})]}),(0,w.jsx)(`p`,{className:`hc-status`,children:n})]})]})]})}var k=`
uniform float u_time;
uniform float u_radius;
uniform float u_noise_amp;
uniform float u_birth_progress;
uniform float u_voice_amp;

attribute vec3 a_basePosition;

varying float v_depth;
varying float v_alpha;
varying float v_latitude;

void main() {
  vec3 norm = normalize(a_basePosition);
  vec3 spherePos = norm * u_radius;

  // Iki sinus dalgasinin carpimi: organik yuzey bukulmesi
  float waveDisp = sin(a_basePosition.x * 3.0 + u_time * 0.8) *
                   sin(a_basePosition.y * 2.0 + u_time * 0.6) *
                   u_noise_amp;
  spherePos += norm * waveDisp;

  // Ses: genlikle disa dogru nefes alir
  spherePos *= (1.0 + u_voice_amp * 0.15);

  vec3 emerged = mix(vec3(0.0), spherePos, smoothstep(0.0, 1.0, u_birth_progress));

  vec4 mvPos = modelViewMatrix * vec4(emerged, 1.0);
  gl_Position = projectionMatrix * mvPos;

  // 0 = kurenin arkasi, 1 = kameraya bakan on yuz
  float rawDepth = dot(norm, vec3(0.0, 0.0, 1.0));
  v_depth = rawDepth * 0.5 + 0.5;

  float ptSize = mix(1.9, 4.4, v_depth);
  float birthSizeBoost = 1.0 + (1.0 - smoothstep(0.0, 0.7, u_birth_progress)) * 0.29;
  ptSize = ptSize * birthSizeBoost * (1.0 + u_voice_amp * 0.2);
  gl_PointSize = ptSize * (8.0 / -mvPos.z);

  v_alpha = smoothstep(0.0, 0.3, u_birth_progress);
  v_latitude = a_basePosition.y;
}
`,A=`
uniform vec3  u_color_equator;
uniform vec3  u_color_pole;
uniform float u_brightness;
uniform float u_birth_progress;

varying float v_depth;
varying float v_alpha;
varying float v_latitude;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float r = length(uv);
  if (r > 0.5) discard;

  // cekirdek + hale + dagilan isima
  float core = smoothstep(0.35, 0.0, r);
  float halo = smoothstep(0.5, 0.1, r) * 0.4;
  float glow = smoothstep(0.5, 0.0, r) * 0.25;
  float intensity = core + halo + glow;

  // ekvator -> kutup renk gecisi
  vec3 color = mix(u_color_equator, u_color_pole, abs(v_latitude));

  // dogarken beyaza kayan kisa parlama
  float birthGlow = 1.0 - smoothstep(0.0, 0.7, u_birth_progress);
  color = mix(color, vec3(1.0, 0.95, 0.9), birthGlow * 0.24);
  float birthBrightBoost = 1.0 + birthGlow * 0.3;

  float depthAlpha = 0.18 + 0.67 * v_depth;
  float glowMult = v_depth > 0.45 ? 1.0 + (v_depth - 0.45) * 1.2 : 0.7;
  float alpha = intensity * v_alpha * depthAlpha;

  // parlak renkleri biraz bastir, koyulari koru
  float lum = dot(color, vec3(0.299, 0.587, 0.114));
  float lumCompensation = mix(1.0, 0.7, lum);

  gl_FragColor = vec4(
    color * u_brightness * birthBrightBoost * glowMult * intensity * lumCompensation,
    alpha
  );
}
`,j=new a(p.equator),M=new a(p.pole),N=new a,P=new a,F=4,I=2500,L=1.5,R=.16,z=-25,B=4.4,V=1.6,H=.75,U=2.5,W=.8,G=new r;function K(e){let t=new Float32Array(e*3),n=Math.PI*(3-Math.sqrt(5));for(let r=0;r<e;r++){let i=1-r/(e-1)*2,a=Math.sqrt(Math.max(0,1-i*i)),o=n*r;t[r*3]=Math.cos(o)*a,t[r*3+1]=i,t[r*3+2]=Math.sin(o)*a}return t}function q(){let e=(0,d.useRef)(null),t=(0,d.useRef)(null),{size:n,camera:r}=c(),a=(0,d.useMemo)(()=>K(I),[]),o=(0,d.useMemo)(()=>({u_time:{value:0},u_radius:{value:L},u_noise_amp:{value:R},u_birth_progress:{value:1},u_voice_amp:{value:0},u_brightness:{value:B},u_color_equator:{value:j.clone()},u_color_pole:{value:M.clone()}}),[]),s=(0,d.useRef)({z,bright:B,amp:0,think:0,spin:0,introAt:-1,landed:!1});return i(({clock:i},a)=>{let o=e.current,c=t.current;if(!o||!c)return;let l=s.current;a=Math.min(a,.1),l.introAt!==p.introAt&&(l.introAt=p.introAt,l.z=z,l.bright=B,l.landed=!1),l.z+=(0-l.z)*U*a,!l.landed&&Math.abs(l.z)<.02&&(l.landed=!0,_.set({landed:!0}),b(`landed`));let u=p.amp;l.amp=u>l.amp?l.amp*.15+u*.85:l.amp*.82+u*.18;let d=+!!p.thinking;l.think+=(d-l.think)*Math.min(1,(p.thinking?5:1.2)*a),l.think<.01&&(l.think=0),l.spin+=a*l.think*.4;let f=p.asleep?H:V;l.bright+=(f-l.bright)*U*a;let m=i.getElapsedTime(),h=Math.min(1,F*a);c.uniforms.u_color_equator.value.lerp(N.set(p.equator),h),c.uniforms.u_color_pole.value.lerp(P.set(p.pole),h);let g=p.persona===`ultron`,v=p.persona===`friday`,y=g?Math.random()<.04?.22:.05:0;c.uniforms.u_time.value=m,c.uniforms.u_voice_amp.value=l.amp,c.uniforms.u_noise_amp.value=R*(p.asleep?.6:1)*(v?.75:1)+l.amp*.52+l.think*.08+y,c.uniforms.u_brightness.value=l.bright+l.amp*6.96+l.think*1.8,o.rotation.y=m*(v?.09:g?.22:.15)+l.spin;let x=r,S=Math.min(176,n.height*.4),C=Math.max(80,n.height-S-12),w=Math.min(C*.34,n.width*.26),T=12+C/2;G.set(0,1-T/n.height*2,.5).unproject(x).sub(x.position).normalize();let E=-x.position.z/G.z,D=2*Math.tan(x.fov*Math.PI/360)*Math.abs(x.position.z)/n.height;o.scale.setScalar(w*D/L),o.position.set(x.position.x+G.x*E,x.position.y+G.y*E,l.z)}),(0,w.jsx)(`group`,{ref:e,position:[0,W,z],children:(0,w.jsxs)(`points`,{frustumCulled:!1,children:[(0,w.jsxs)(`bufferGeometry`,{children:[(0,w.jsx)(`bufferAttribute`,{attach:`attributes-position`,args:[a,3]}),(0,w.jsx)(`bufferAttribute`,{attach:`attributes-a_basePosition`,args:[a,3]})]}),(0,w.jsx)(`shaderMaterial`,{ref:t,vertexShader:k,fragmentShader:A,uniforms:o,transparent:!0,depthWrite:!1,blending:2})]})})}function J({onReady:e}){let t=v(e=>e.active),n=typeof window<`u`&&window.innerWidth<768;return(0,w.jsxs)(o,{className:`orb-canvas`,frameloop:t?`always`:`never`,dpr:[1,2],camera:{position:[0,W,5.5],fov:n?56:50},gl:{alpha:!0,antialias:!0,powerPreference:`high-performance`},onCreated:()=>e(),children:[(0,w.jsx)(q,{}),(0,w.jsx)(s,{multisampling:8,frameBufferType:u,children:(0,w.jsx)(l,{luminanceThreshold:.35,luminanceSmoothing:.9,intensity:.9,radius:.7,mipmapBlur:!0})})]})}function Y(){try{return!!document.createElement(`canvas`).getContext(`webgl2`)}catch{return!1}}var X=Y();function Z(){return(0,d.useEffect)(()=>{let e=x();return X||b(`error`),e},[]),(0,w.jsxs)(`main`,{className:`orb-page`,children:[X&&(0,w.jsx)(J,{onReady:()=>b(`ready`)}),(0,w.jsx)(O,{})]})}export{Z as default};