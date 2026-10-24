// Sade cevre efektleri: hologram yayici zemin, lazer tarama halkasi ve Arc Reactor
// ateslenirken bir an gorunen enerji arklari.
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { anim } from '../store'
import { REACTOR_POS } from './armorParts'
import { HOLO } from './materials'

const HALF_PI = Math.PI / 2

/** Zemin: soluk izgara + zirhin altinda hologram yayici halka. */
function Floor() {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: { uOn: { value: 0 }, uColor: { value: new THREE.Color(HOLO) } },
        vertexShader: /* glsl */ `
          varying vec2 vUv;
          void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
        fragmentShader: /* glsl */ `
          varying vec2 vUv;
          uniform float uOn;
          uniform vec3 uColor;
          float line(float v, float w) { float f = abs(fract(v) - 0.5); return smoothstep(w, 0.0, f); }
          void main() {
            vec2 p = (vUv - 0.5) * 10.0;
            float r = length(p);
            float grid = max(line(p.x * 2.0 + 0.5, 0.02), line(p.y * 2.0 + 0.5, 0.02)) * 0.16 * smoothstep(4.6, 0.8, r);
            float emitter = smoothstep(0.012, 0.0, abs(r - 0.5)) * 0.9 + smoothstep(0.006, 0.0, abs(r - 0.62)) * 0.4;
            float pool = smoothstep(0.62, 0.0, r) * 0.18;
            float v = (grid + emitter + pool) * uOn;
            gl_FragColor = vec4(uColor * v, v);
          }`,
      }),
    [],
  )
  useFrame(() => {
    material.uniforms.uOn.value = anim.grid
  })
  return (
    <mesh rotation={[-HALF_PI, 0, 0]} position={[0, -0.002, 0]} material={material}>
      <planeGeometry args={[10, 10]} />
    </mesh>
  )
}

/** Lazer tarama halkasi: o an kurulan bolgenin yuksekliginde gezer. */
function Scan() {
  const group = useRef<THREE.Group>(null)
  const ring = useMemo(
    () => new THREE.MeshBasicMaterial({ color: new THREE.Color(HOLO).multiplyScalar(1.8), transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, toneMapped: false }),
    [],
  )
  useFrame(() => {
    if (!group.current) return
    group.current.visible = anim.scan > 0.01
    group.current.position.y = anim.scanY
    ring.opacity = anim.scan
  })
  return (
    <group ref={group} rotation={[-HALF_PI, 0, 0]}>
      <mesh material={ring}>
        <ringGeometry args={[0.5, 0.506, 96]} />
      </mesh>
    </group>
  )
}

/** Reactor ateslenirken cevreye sicrayan kisa omurlu arklar. */
function Arcs() {
  const COUNT = 4
  const SEG = 12
  const lines = useMemo(() => {
    const material = new THREE.LineBasicMaterial({ color: new THREE.Color(HOLO).multiplyScalar(2.2), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false })
    return Array.from({ length: COUNT }, () => {
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(SEG * 3), 3))
      const line = new THREE.Line(geometry, material)
      line.frustumCulled = false
      return line
    })
  }, [])
  const next = useRef(0)
  useFrame((state) => {
    const on = anim.arcs > 0.02
    ;(lines[0].material as THREE.LineBasicMaterial).opacity = anim.arcs
    lines.forEach((l) => (l.visible = on))
    if (!on || state.clock.elapsedTime < next.current) return
    next.current = state.clock.elapsedTime + 0.06
    for (const line of lines) {
      const a = Math.random() * Math.PI * 2
      const reach = 0.18 + Math.random() * 0.3
      const attr = line.geometry.getAttribute('position') as THREE.BufferAttribute
      for (let i = 0; i < SEG; i++) {
        const k = i / (SEG - 1)
        const jitter = Math.sin(k * Math.PI) * 0.045
        attr.setXYZ(
          i,
          REACTOR_POS[0] + Math.cos(a) * reach * k + (Math.random() - 0.5) * jitter,
          REACTOR_POS[1] + Math.sin(a) * reach * k + (Math.random() - 0.5) * jitter,
          REACTOR_POS[2] + (Math.random() - 0.5) * jitter,
        )
      }
      attr.needsUpdate = true
    }
  })
  return (
    <>
      {lines.map((line, i) => (
        <primitive key={i} object={line} />
      ))}
    </>
  )
}

export default function Fx() {
  return (
    <>
      <Floor />
      <Scan />
      <Arcs />
    </>
  )
}
