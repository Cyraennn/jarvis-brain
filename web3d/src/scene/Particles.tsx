// Parcacik bulutu: uzaydan gelen noktalar sirasi gelen zirh parcasina akar ve yuzeye karisir.
import { useFrame } from '@react-three/fiber'
import { useMemo } from 'react'
import * as THREE from 'three'
import { anim, GROUPS } from '../store'
import { PARTS } from './armorParts'

const COUNT = 1200

export default function Particles() {
  const { geometry, material } = useMemo(() => {
    const start = new Float32Array(COUNT * 3)
    const target = new Float32Array(COUNT * 3)
    const delay = new Float32Array(COUNT)
    const seed = new Float32Array(COUNT)
    const order = (g: (typeof GROUPS)[number]) => GROUPS.indexOf(g) / GROUPS.length

    for (let i = 0; i < COUNT; i++) {
      const part = PARTS[Math.floor(Math.random() * PARTS.length)]
      // baslangic: zirhi saran kure kabugu
      const u = Math.random() * Math.PI * 2
      const v = Math.acos(2 * Math.random() - 1)
      const radius = 1.7 + Math.random() * 1.6
      start[i * 3] = Math.sin(v) * Math.cos(u) * radius
      start[i * 3 + 1] = 1 + Math.cos(v) * radius * 0.8
      start[i * 3 + 2] = Math.sin(v) * Math.sin(u) * radius
      // hedef: parcanin cevresi
      const spread = 0.07
      target[i * 3] = part.pos[0] + (Math.random() - 0.5) * spread * 2
      target[i * 3 + 1] = part.pos[1] + (Math.random() - 0.5) * spread * 3
      target[i * 3 + 2] = part.pos[2] + (Math.random() - 0.5) * spread * 2
      delay[i] = order(part.group) * 0.82 + Math.random() * 0.08
      seed[i] = Math.random()
    }

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(start, 3))
    geometry.setAttribute('aTarget', new THREE.BufferAttribute(target, 3))
    geometry.setAttribute('aDelay', new THREE.BufferAttribute(delay, 1))
    geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
    geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 1, 0), 5)

    const material = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: { uT: { value: 0 }, uSpin: { value: 0 }, uTime: { value: 0 }, uScale: { value: 1 } },
      vertexShader: /* glsl */ `
        attribute vec3 aTarget;
        attribute float aDelay;
        attribute float aSeed;
        uniform float uT;
        uniform float uSpin;
        uniform float uTime;
        uniform float uScale;
        varying float vAlpha;
        void main() {
          float local = clamp((uT - aDelay) / 0.14, 0.0, 1.0);
          float ease = local * local * (3.0 - 2.0 * local);
          // hedef zirhla birlikte doner
          float c = cos(uSpin), s = sin(uSpin);
          vec3 tgt = vec3(aTarget.x * c + aTarget.z * s, aTarget.y, -aTarget.x * s + aTarget.z * c);
          vec3 p = mix(position, tgt, ease);
          // yolda sarmal salinim
          float swirl = (1.0 - ease) * ease * 1.2;
          p.x += sin(uTime * 2.0 + aSeed * 40.0) * swirl * 0.35;
          p.z += cos(uTime * 2.3 + aSeed * 31.0) * swirl * 0.35;
          vAlpha = sin(local * 3.14159) * (0.5 + 0.5 * aSeed);
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          gl_Position = projectionMatrix * mv;
          gl_PointSize = uScale * (1.2 + aSeed * 1.8) * (3.0 / -mv.z);
        }`,
      fragmentShader: /* glsl */ `
        varying float vAlpha;
        void main() {
          float d = length(gl_PointCoord - 0.5);
          float a = smoothstep(0.5, 0.0, d) * vAlpha;
          if (a < 0.01) discard;
          gl_FragColor = vec4(vec3(0.39, 0.82, 1.0) * 1.3, a);
        }`,
    })
    return { geometry, material }
  }, [])

  useFrame((state) => {
    material.uniforms.uT.value = anim.particles
    material.uniforms.uSpin.value = anim.spin
    material.uniforms.uTime.value = state.clock.elapsedTime
    material.uniforms.uScale.value = state.gl.getPixelRatio()
    material.visible = anim.particles > 0.001 && anim.particles < 1.14
  })

  return <points geometry={geometry} material={material} frustumCulled={false} />
}
