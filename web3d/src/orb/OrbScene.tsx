// Zoey OS hero orb'u: 2500 parcacikli isik kuresi, uzaktan suzulerek gelir, yavasca doner,
// konusurken genlikle nefes alir, "dusunurken" hizlanir. Isik yok; parlama tamamen Bloom'dan.
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer } from '@react-three/postprocessing'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { orbFragment, orbVertex } from './shaders'
import { live, notify, orb, useOrb } from './voice'

// Baslangic renkleri CYRAEN temasi; Qt setTheme ile kisilige gore degisir (live.equator/pole)
const EQUATOR = new THREE.Color(live.equator)
const POLE = new THREE.Color(live.pole)
const TARGET_EQ = new THREE.Color()
const TARGET_POLE = new THREE.Color()
const COLOR_EASE = 4.0        // ~0.6 sn'de yeni kisilik rengine gecis

const PARTICLES = 2500
const RADIUS = 1.5
const NOISE_AMP = 0.16
const START_Z = -25           // orb uzaktan gelir
const START_BRIGHT = 4.4      // gelirken parlak, yerine oturunca sakinlesir
const REST_BRIGHT = 1.6
const ASLEEP_BRIGHT = 0.75
const SETTLE = 2.5            // ustel yaklasma hizi (1/sn)
const CAMERA_Y = 0.8
const RAY = new THREE.Vector3()

/** Orb'un altinda HTML arayuzune (alt yazi + hap + durum) birakilan yukseklik (px). */
export const HUD_RESERVE_PX = 176

function fibonacciSphere(n: number): Float32Array {
  const out = new Float32Array(n * 3)
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2
    const r = Math.sqrt(Math.max(0, 1 - y * y))
    const a = golden * i
    out[i * 3] = Math.cos(a) * r
    out[i * 3 + 1] = y
    out[i * 3 + 2] = Math.sin(a) * r
  }
  return out
}

function Orb() {
  const group = useRef<THREE.Group>(null)
  const material = useRef<THREE.ShaderMaterial>(null)
  const { size, camera } = useThree()
  const positions = useMemo(() => fibonacciSphere(PARTICLES), [])
  const uniforms = useMemo(
    () => ({
      u_time: { value: 0 },
      u_radius: { value: RADIUS },
      u_noise_amp: { value: NOISE_AMP },
      u_birth_progress: { value: 1 },
      u_voice_amp: { value: 0 },
      u_brightness: { value: START_BRIGHT },
      u_color_equator: { value: EQUATOR.clone() },
      u_color_pole: { value: POLE.clone() },
    }),
    [],
  )
  const s = useRef({ z: START_Z, bright: START_BRIGHT, amp: 0, think: 0, spin: 0, introAt: -1, landed: false })

  useFrame(({ clock }, dt) => {
    const g = group.current
    const m = material.current
    if (!g || !m) return
    const st = s.current
    dt = Math.min(dt, 0.1)

    if (st.introAt !== live.introAt) {          // ilk acilis ya da Qt'den intro()
      st.introAt = live.introAt
      st.z = START_Z
      st.bright = START_BRIGHT
      st.landed = false
    }
    st.z += (0 - st.z) * SETTLE * dt
    if (!st.landed && Math.abs(st.z) < 0.02) {
      st.landed = true
      orb.set({ landed: true })
      notify('landed')
    }

    // Zoey'nin genlik yumusatmasi: hizli atak, yavas birakis
    const target = live.amp
    st.amp = target > st.amp ? st.amp * 0.15 + target * 0.85 : st.amp * 0.82 + target * 0.18
    const thinking = live.thinking ? 1 : 0
    st.think += (thinking - st.think) * Math.min(1, (live.thinking ? 5 : 1.2) * dt)
    if (st.think < 0.01) st.think = 0
    st.spin += dt * st.think * 0.4

    const rest = live.asleep ? ASLEEP_BRIGHT : REST_BRIGHT
    st.bright += (rest - st.bright) * SETTLE * dt

    const t = clock.getElapsedTime()
    const k = Math.min(1, COLOR_EASE * dt)
    ;(m.uniforms.u_color_equator.value as THREE.Color).lerp(TARGET_EQ.set(live.equator), k)
    ;(m.uniforms.u_color_pole.value as THREE.Color).lerp(TARGET_POLE.set(live.pole), k)
    // ULTRON: huzursuz, titrek kure; FRIDAY: sakin ve yavas donus
    const ultron = live.persona === 'ultron'
    const friday = live.persona === 'friday'
    const jitter = ultron ? (Math.random() < 0.04 ? 0.22 : 0.05) : 0
    m.uniforms.u_time.value = t
    m.uniforms.u_voice_amp.value = st.amp
    m.uniforms.u_noise_amp.value =
      NOISE_AMP * (live.asleep ? 0.6 : 1) * (friday ? 0.75 : 1) + st.amp * 0.52 + st.think * 0.08 + jitter
    m.uniforms.u_brightness.value = st.bright + st.amp * 6.96 + st.think * 1.8
    g.rotation.y = t * (friday ? 0.09 : ultron ? 0.22 : 0.15) + st.spin

    // Yerlesim: orb, alttaki HTML arayuzunun ustunde kalan alanin ortasina sigdirilir.
    // r3f kamerayi orijine baktirdigi icin ekran noktasi z=0 duzlemine izdusurulur (Zoey'deki gibi).
    const cam = camera as THREE.PerspectiveCamera
    const reserve = Math.min(HUD_RESERVE_PX, size.height * 0.4)
    const areaH = Math.max(80, size.height - reserve - 12)
    const radiusPx = Math.min(areaH * 0.34, size.width * 0.26)
    const centerPx = 12 + areaH / 2
    RAY.set(0, 1 - (centerPx / size.height) * 2, 0.5).unproject(cam).sub(cam.position).normalize()
    const dist = -cam.position.z / RAY.z
    const unitsPerPx = (2 * Math.tan((cam.fov * Math.PI) / 360) * Math.abs(cam.position.z)) / size.height
    g.scale.setScalar((radiusPx * unitsPerPx) / RADIUS)
    g.position.set(cam.position.x + RAY.x * dist, cam.position.y + RAY.y * dist, st.z)
  })

  return (
    <group ref={group} position={[0, CAMERA_Y, START_Z]}>
      <points frustumCulled={false}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-a_basePosition" args={[positions, 3]} />
        </bufferGeometry>
        <shaderMaterial
          ref={material}
          vertexShader={orbVertex}
          fragmentShader={orbFragment}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
    </group>
  )
}

export default function OrbScene({ onReady }: { onReady: () => void }) {
  const active = useOrb((v) => v.active)
  const narrow = typeof window !== 'undefined' && window.innerWidth < 768
  return (
    <Canvas
      className="orb-canvas"
      frameloop={active ? 'always' : 'never'}
      dpr={[1, 2]}
      camera={{ position: [0, CAMERA_Y, 5.5], fov: narrow ? 56 : 50 }}
      gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
      onCreated={() => onReady()}
    >
      <Orb />
      <EffectComposer multisampling={8} frameBufferType={THREE.HalfFloatType}>
        <Bloom luminanceThreshold={0.35} luminanceSmoothing={0.9} intensity={0.9} radius={0.7} mipmapBlur />
      </EffectComposer>
    </Canvas>
  )
}
