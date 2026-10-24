// Hologram zirh: her parca derinlik + kabuk + kenar cizgisi olarak cizilir; Arc Reactor, gozler
// ve iticiler sicak noktalardir. Hiyerarsi: kok (donus, suzulme) -> govde (nefes, imleci hafif
// izler) + kafa (imleci izler).
import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { anim, GROUPS, type Group as GroupName, type Phase } from '../store'
import { BODY_PIVOT, EYE_POS, GROUP_ORIGIN, HEAD_PIVOT, PALM_POS, PARTS, REACTOR_POS, type Part } from './armorParts'
import { depthOnly, holoEdges, holoShell, HOT_COLOR, hotMaterial, shared, type RevealUniforms } from './materials'

type Slot = { group: GroupName; reveal: RevealUniforms; depth: THREE.Material; shell: THREE.Material; edges: THREE.Material }

function buildMaterials() {
  const slots = new Map<string, Slot>()
  const hot = { core: hotMaterial(), eye: hotMaterial(), repulsor: hotMaterial() }

  const slotFor = (part: Part): Slot => {
    const key = `${part.group}:${part.side}`
    let slot = slots.get(key)
    if (!slot) {
      const { at, reach } = GROUP_ORIGIN[part.group]
      // orta hat parcalari grubun iki yanina esit uzaklikta olussun diye x = 0 alinir
      const reveal: RevealUniforms = {
        uProgress: { value: 0 },
        uLines: { value: 0 },
        uOrigin: { value: new THREE.Vector3(at[0] * part.side, at[1], at[2]) },
        uReach: { value: reach + (part.side === 0 ? Math.abs(at[0]) : 0) },
      }
      slot = { group: part.group, reveal, depth: depthOnly(reveal), shell: holoShell(reveal), edges: holoEdges(reveal) }
      slots.set(key, slot)
    }
    return slot
  }

  const items = PARTS.map((part) => ({ part, slot: slotFor(part) }))
  return { items, slots: [...slots.values()], hot }
}

const sub = (a: readonly number[], b: readonly number[]): [number, number, number] => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]

/** Parcaya ince bir cizgiyle baglanan etiket (yalnizca bosta gorunur). */
function Callout({ at, label, value, side = 1, reach = 56 }: { at: readonly number[]; label: string; value: string; side?: 1 | -1; reach?: number }) {
  return (
    <Html position={[at[0], at[1], at[2]]} zIndexRange={[5, 0]} style={{ pointerEvents: 'none' }}>
      <div className={`flex items-center ${side === 1 ? '' : '-translate-x-full flex-row-reverse'}`}>
        <span className="h-1 w-1 rounded-full bg-arc" />
        <span className="h-0.5 bg-arc/50" style={{ width: reach }} />
        <span className={`whitespace-nowrap font-mono text-[0.62rem] leading-tight tracking-[0.16em] ${side === 1 ? 'pl-2' : 'pr-2 text-right'}`}>
          <span className="block text-arc">{label}</span>
          <span className="block text-ink/60">{value}</span>
        </span>
      </div>
    </Html>
  )
}

export default function Armor({ phase }: { phase: Phase }) {
  const root = useRef<THREE.Group>(null)
  const body = useRef<THREE.Group>(null)
  const head = useRef<THREE.Group>(null)
  const { items, slots, hot } = useMemo(buildMaterials, [])
  const idle = phase === 'idle'

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime
    const settled = phase === 'idle' || phase === 'leaving'
    const r = root.current
    if (!r) return

    // --- kok: acilista 360 derece donus, sonra suzulme
    r.rotation.y = anim.spin
    r.position.y = settled ? Math.sin(t * 1.1) * 0.016 : 0
    r.updateWorldMatrix(true, false)
    shared.uRootInv.value.copy(r.matrixWorld).invert()
    shared.uTime.value = t

    // --- olusma degerleri
    for (const slot of slots) {
      const solid = anim.solid[slot.group]
      const lines = anim.holo[slot.group]
      slot.reveal.uProgress.value = solid
      slot.reveal.uLines.value = lines
      slot.depth.visible = slot.shell.visible = solid > 0.001
      slot.edges.visible = lines > 0.001
    }

    // --- sicak noktalar: reactor hafifce nabiz atar
    const pulse = 1 + Math.sin(t * 2.4) * 0.07
    hot.core.color.copy(HOT_COLOR).multiplyScalar(anim.reactor * 2.6 * pulse)
    hot.eye.color.copy(HOT_COLOR).multiplyScalar(anim.eyes * 2.4)
    hot.repulsor.color.copy(HOT_COLOR).multiplyScalar(anim.repulsors * 2.0)
    hot.core.visible = anim.reactor > 0.01
    hot.eye.visible = anim.eyes > 0.01
    hot.repulsor.visible = anim.repulsors > 0.01

    // --- bosta: nefes + imleci izleme (yumusak)
    const k = 1 - Math.exp(-delta * 4)
    const px = settled ? state.pointer.x : 0
    const py = settled ? state.pointer.y : 0
    if (head.current) {
      head.current.rotation.y += (px * 0.5 - head.current.rotation.y) * k
      head.current.rotation.x += (-py * 0.22 - head.current.rotation.x) * k
    }
    if (body.current) {
      body.current.rotation.y += (px * 0.12 - body.current.rotation.y) * k
      const breath = settled ? 1 + Math.sin(t * 1.5) * 0.005 : 1
      body.current.scale.set(breath, 1, breath)
    }
  })

  const render = (inHead: boolean) =>
    items
      .filter(({ part }) => (part.group === 'helmet') === inHead)
      .map(({ part, slot }, i) => {
        const pos = sub(part.pos, inHead ? HEAD_PIVOT : BODY_PIVOT)
        return (
          <group key={i} position={pos} rotation={part.rot} scale={part.scale}>
            {part.kind === 'shell' ? (
              <>
                <mesh geometry={part.geo} material={slot.depth} renderOrder={0} />
                <mesh geometry={part.geo} material={slot.shell} renderOrder={1} />
                {part.edges && <lineSegments geometry={part.edges} material={slot.edges} renderOrder={2} />}
              </>
            ) : (
              <mesh geometry={part.geo} material={hot[part.kind]} renderOrder={3} />
            )}
          </group>
        )
      })

  return (
    <group ref={root}>
      <group ref={body} position={BODY_PIVOT}>
        {render(false)}
        {idle && <Callout at={sub(REACTOR_POS, BODY_PIVOT)} label="ARC REAKTÖR" value="KARARLI · %100" reach={190} />}
        {idle && <Callout at={sub([-PALM_POS[0], PALM_POS[1], PALM_POS[2]], BODY_PIVOT)} label="REPULSÖR" value="ŞARJLI" side={-1} />}
      </group>
      <group ref={head} position={HEAD_PIVOT}>
        {render(true)}
        {idle && <Callout at={sub(EYE_POS, HEAD_PIVOT)} label="OPTİK" value="AKTİF" reach={90} />}
      </group>
    </group>
  )
}
