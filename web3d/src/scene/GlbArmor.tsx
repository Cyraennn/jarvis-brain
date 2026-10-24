// Harici model yuvasi: public/models/armor.glb varsa prosedurel zirh yerine o yuklenir.
// Model ~1.9 birim boya olceklenir, ayaklari y = 0'a oturtulur ve kendi malzemeleri yerine
// ayni hologram katmanlari (derinlik + kabuk + kenar cizgisi) uygulanir. Olusma, gogus
// noktasindan disari dogru tek dalga halinde ilerler.
import { useGLTF } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { anim, type Phase } from '../store'
import { depthOnly, holoEdges, holoShell, shared, type RevealUniforms } from './materials'

export const GLB_URL = './models/armor.glb'
const HEIGHT = 1.9
const CHEST = new THREE.Vector3(0, HEIGHT * 0.73, 0.1)
const MAX_EDGE_TRIANGLES = 200_000 // cok yogun modellerde kenar cizgisi cikarmak pahali ve kalabalik

export default function GlbArmor({ phase }: { phase: Phase }) {
  const root = useRef<THREE.Group>(null)
  const { scene } = useGLTF(GLB_URL)

  const { model, reveal } = useMemo(() => {
    const reveal: RevealUniforms = {
      uProgress: { value: 0 },
      uLines: { value: 0 },
      uOrigin: { value: CHEST.clone() },
      uReach: { value: HEIGHT * 0.78 },
    }
    const depth = depthOnly(reveal)
    const shell = holoShell(reveal)
    const edges = holoEdges(reveal)

    const model = scene.clone(true)
    const box = new THREE.Box3().setFromObject(model)
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const scale = HEIGHT / Math.max(size.y, 1e-6)
    model.scale.setScalar(scale)
    model.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale)

    const meshes: THREE.Mesh[] = []
    model.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) meshes.push(obj as THREE.Mesh)
    })
    for (const mesh of meshes) {
      mesh.material = depth
      mesh.renderOrder = 0
      const skin = new THREE.Mesh(mesh.geometry, shell)
      skin.renderOrder = 1
      mesh.add(skin)
      const triangles = (mesh.geometry.index?.count ?? mesh.geometry.getAttribute('position').count) / 3
      if (triangles <= MAX_EDGE_TRIANGLES) {
        const lines = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 32), edges)
        lines.renderOrder = 2
        mesh.add(lines)
      }
    }
    return { model, reveal }
  }, [scene])

  useFrame((state, delta) => {
    const r = root.current
    if (!r) return
    const t = state.clock.elapsedTime
    const settled = phase === 'idle' || phase === 'leaving'
    const k = 1 - Math.exp(-delta * 4)
    // acilis donusu + bosta imleci hafifce izleme
    const follow = settled ? state.pointer.x * 0.25 : 0
    r.userData.follow = (r.userData.follow ?? 0) + (follow - (r.userData.follow ?? 0)) * k
    r.rotation.y = anim.spin + r.userData.follow
    r.position.y = settled ? Math.sin(t * 1.1) * 0.016 : 0
    r.updateWorldMatrix(true, false)
    shared.uRootInv.value.copy(r.matrixWorld).invert()
    shared.uTime.value = t
    reveal.uProgress.value = anim.glb
    reveal.uLines.value = Math.min(1, anim.glb * 1.25)
  })

  return (
    <group ref={root}>
      <primitive object={model} />
    </group>
  )
}
