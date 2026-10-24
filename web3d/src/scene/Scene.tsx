// Sahne: hologram kendi isigini urettigi icin isik ya da ortam haritasi yoktur; yalnizca
// kamera, zirh, sade efektler ve hafif bir Bloom.
import { OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import { Suspense, useRef } from 'react'
import * as THREE from 'three'
import { anim, type Phase } from '../store'
import Armor from './Armor'
import Fx from './Fx'
import GlbArmor from './GlbArmor'
import Particles from './Particles'

const TARGET = new THREE.Vector3(0, 0.96, 0)
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

/** Acilista sinematik dolly-zoom (yaklasirken gorus acisi genisler); bosta kontrol kullaniciya gecer. */
function CameraRig({ phase }: { phase: Phase }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const done = useRef(false)
  useFrame(() => {
    if (done.current) return
    const idle = phase === 'idle' || phase === 'leaving'
    // bosta ilk karede bitis pozuna oturur, sonra OrbitControls devralir
    const d = idle ? 1 : anim.dolly
    camera.position.set(Math.sin(d * 0.9) * 0.3, lerp(1.5, 1.1, d), lerp(7.2, 4.6, d))
    camera.fov = lerp(24, 33, d)
    camera.lookAt(TARGET)
    camera.updateProjectionMatrix()
    done.current = idle
  })
  return (
    <OrbitControls
      makeDefault
      enabled={phase === 'idle'}
      target={TARGET}
      enablePan={false}
      enableDamping
      dampingFactor={0.08}
      rotateSpeed={0.7}
      zoomSpeed={0.7}
      minDistance={2.2}
      maxDistance={6.5}
      minPolarAngle={0.95}
      maxPolarAngle={1.78}
    />
  )
}

export default function Scene({ phase, useGlb, onReady }: { phase: Phase; useGlb: boolean; onReady: () => void }) {
  return (
    <Canvas
      flat
      dpr={[1, 1.5]}
      gl={{ antialias: false, powerPreference: 'high-performance', alpha: false }}
      camera={{ fov: 24, near: 0.1, far: 60, position: [0, 1.5, 7.2] }}
      onCreated={({ gl }) => {
        gl.setClearColor('#03070d')
        onReady()
      }}
    >
      <Suspense fallback={null}>{useGlb ? <GlbArmor phase={phase} /> : <Armor phase={phase} />}</Suspense>
      <Particles />
      <Fx />
      <CameraRig phase={phase} />

      <EffectComposer multisampling={4} frameBufferType={THREE.HalfFloatType}>
        <Bloom mipmapBlur intensity={0.55} luminanceThreshold={0.85} luminanceSmoothing={0.2} radius={0.7} />
        <Vignette eskil={false} offset={0.25} darkness={0.7} />
      </EffectComposer>
    </Canvas>
  )
}
