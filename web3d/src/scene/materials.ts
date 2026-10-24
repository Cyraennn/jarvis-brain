// Hologram malzemeleri. Zirh uc katmanda cizilir:
//   1. depthOnly  : yalnizca derinlik yazar -> ust uste binen parcalarin ic yuzleri gorunmez,
//                   zirh tek bir govde gibi okunur.
//   2. holoShell  : kenarlari parlayan (fresnel), ici neredeyse saydam kabuk + tarama cizgileri.
//   3. holoEdges  : panel kenar cizgileri (EdgesGeometry).
// Ucunde de ayni "olusma" cephesi vardir: grubun cikis noktasindan disari dogru yayilir.
import * as THREE from 'three'

export type RevealUniforms = {
  uProgress: { value: number } // kabuk (yuzey) ne kadar olustu
  uLines: { value: number }    // kenar cizgileri ne kadar yayildi (kabuktan once gelir)
  uOrigin: { value: THREE.Vector3 }
  uReach: { value: number }
}

export const HOLO = '#63d2ff'

// Zirh kokunun ters dunya matrisi: efekt zirh donerken de parcaya yapisik kalir.
export const shared = {
  uRootInv: { value: new THREE.Matrix4() },
  uTime: { value: 0 },
  uColor: { value: new THREE.Color(HOLO) },
}

const NOISE = /* glsl */ `
float jHash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float jNoise(vec3 x) {
  vec3 i = floor(x);
  vec3 f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(jHash(i), jHash(i + vec3(1, 0, 0)), f.x), mix(jHash(i + vec3(0, 1, 0)), jHash(i + vec3(1, 1, 0)), f.x), f.y),
    mix(mix(jHash(i + vec3(0, 0, 1)), jHash(i + vec3(1, 0, 1)), f.x), mix(jHash(i + vec3(0, 1, 1)), jHash(i + vec3(1, 1, 1)), f.x), f.y),
    f.z);
}
// Cephenin gerisinde kalan parca atilir; donen deger cephenin hemen icindeki ince seritte 1'e cikar.
float jReveal(vec3 p, vec3 origin, float reach, float progress) {
  if (progress >= 0.999) return 0.0;
  float dist = distance(p, origin) + (jNoise(p * 20.0) - 0.5) * 0.07;
  float front = progress * (reach + 0.1);
  if (dist > front) discard;
  return smoothstep(front - 0.07, front, dist);
}
`

// Uc katman da ayni kose donusumunu kullanir: derinlik degerleri birebir esit cikar.
const VERTEX = /* glsl */ `
uniform mat4 uRootInv;
varying vec3 vRootPos;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vRootPos = (uRootInv * world).xyz;
  vec4 mv = viewMatrix * world;
  vNormal = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`

const revealUniforms = (r: RevealUniforms, progress: { value: number }) => ({
  uProgress: progress,
  uOrigin: r.uOrigin,
  uReach: r.uReach,
  uRootInv: shared.uRootInv,
  uTime: shared.uTime,
  uColor: shared.uColor,
})

const FRAG_HEAD = /* glsl */ `
uniform float uProgress;
uniform vec3 uOrigin;
uniform float uReach;
uniform float uTime;
uniform vec3 uColor;
varying vec3 vRootPos;
varying vec3 vNormal;
varying vec3 vView;
${NOISE}
`

export function depthOnly(reveal: RevealUniforms): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    colorWrite: false,
    side: THREE.DoubleSide,
    uniforms: revealUniforms(reveal, reveal.uProgress),
    vertexShader: VERTEX,
    fragmentShader: /* glsl */ `${FRAG_HEAD}
      void main() {
        jReveal(vRootPos, uOrigin, uReach, uProgress);
        gl_FragColor = vec4(0.0);
      }`,
  })
}

export function holoShell(reveal: RevealUniforms): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    uniforms: revealUniforms(reveal, reveal.uProgress),
    vertexShader: VERTEX,
    fragmentShader: /* glsl */ `${FRAG_HEAD}
      void main() {
        float edge = jReveal(vRootPos, uOrigin, uReach, uProgress);
        float fresnel = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.4);
        // ince yatay tarama cizgileri + asagidan yukari kayan yumusak bant
        float scan = 0.82 + 0.18 * sin(vRootPos.y * 260.0);
        float band = smoothstep(0.06, 0.0, abs(fract(vRootPos.y * 0.55 - uTime * 0.16) - 0.5) - 0.44);
        float flicker = 0.94 + 0.06 * sin(uTime * 31.0) * sin(uTime * 7.3);
        float glow = (0.05 + fresnel * 0.95 + band * 0.12) * scan * flicker + edge * 1.6;
        gl_FragColor = vec4(uColor * glow, 1.0);
      }`,
  })
}

export function holoEdges(reveal: RevealUniforms): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: revealUniforms(reveal, reveal.uLines),
    vertexShader: /* glsl */ `
      uniform mat4 uRootInv;
      varying vec3 vRootPos;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vRootPos = (uRootInv * world).xyz;
        gl_Position = projectionMatrix * viewMatrix * world;
        gl_Position.z -= 0.0006 * gl_Position.w;   // cizgi kendi yuzeyinin hemen onunde kalsin
      }`,
    fragmentShader: /* glsl */ `
      uniform float uProgress;
      uniform vec3 uOrigin;
      uniform float uReach;
      uniform vec3 uColor;
      varying vec3 vRootPos;
      ${NOISE}
      void main() {
        float edge = jReveal(vRootPos, uOrigin, uReach, uProgress);
        gl_FragColor = vec4(uColor * (0.55 + edge * 2.2), 1.0);
      }`,
  })
}

/** Sicak noktalar (Arc Reactor, gozler, iticiler): parlakligi her karede `anim`'den gelir, Bloom yakalar. */
export function hotMaterial(): THREE.MeshBasicMaterial {
  return new THREE.MeshBasicMaterial({ color: '#000000', toneMapped: false })
}

export const HOT_COLOR = new THREE.Color('#dff6ff')
