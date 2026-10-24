// Acilis sirasi (GSAP): karanlik -> Arc Reactor -> govde -> asagi ayaklara -> yukari kollara -> kask.
// Her grupta once kenar cizgileri yayilir, ardindan hologram kabugu ayni cepheyle oturur.
import gsap from 'gsap'
import { anim, GROUPS, hud, type Group } from './store'

// Kare hizi dusse de acilis duvar saatine bagli kalsin (uzamasin)
gsap.ticker.lagSmoothing(0)

const LINES_LEAD = 0.22 // cizgiler kabuktan bu kadar once baslar (sn)
const LINES_TIME = 0.5
const SHELL_TIME = 0.65

// [grup, baslangic sn, tarama halkasinin gidecegi yukseklik]
const ORDER: [Group, number, number][] = [
  ['torso', 0.95, 1.05],
  ['pelvis', 1.4, 0.9],
  ['thighs', 1.72, 0.52],
  ['shins', 2.04, 0.12],
  ['boots', 2.36, 0.0],
  ['shoulders', 2.8, 1.42],
  ['arms', 3.08, 1.14],
  ['forearms', 3.36, 0.86],
  ['gloves', 3.64, 0.68],
  ['neck', 3.95, 1.62],
  ['helmet', 4.15, 1.93],
]

const BUILD_START = 0.95
const BUILD_END = 4.8
export const BOOT_SECONDS = 5.6

/** Her seyi bitmis haline getirir (acilissiz "idle" modu icin). */
export function finishInstantly(): void {
  for (const g of GROUPS) {
    anim.solid[g] = 1
    anim.holo[g] = 1
  }
  Object.assign(anim, { reactor: 1, eyes: 1, repulsors: 1, spin: Math.PI * 2, dolly: 1, grid: 1, scan: 0, arcs: 0, particles: 1.2, glb: 1 })
  hud.set({ phase: 'idle', power: 100, stages: hud.get().stages.map((s) => ({ ...s, state: 'hazir' })) })
}

export function createBootTimeline(onIdle: () => void): gsap.core.Timeline {
  const tl = gsap.timeline({ defaults: { ease: 'power2.out' } })
  const say = (at: number, line: string) => tl.call(() => hud.log(line), undefined, at)
  const stage = (at: number, key: string, value: 'kuruluyor' | 'hazir') => tl.call(() => hud.stage(key, value), undefined, at)

  // --- 0.0  karanlik: zemin yayicisi yanar
  tl.call(() => hud.set({ phase: 'boot' }), undefined, 0)
  tl.to(anim, { grid: 1, duration: 0.8, ease: 'power1.inOut' }, 0.05)
  say(0.1, 'Çekirdek yükleniyor')

  // --- 0.45 Arc Reactor atesleme (bir kez titrer, sonra oturur) + kisa arklar
  stage(0.45, 'reactor', 'kuruluyor')
  say(0.45, 'Arc Reaktör ateşleniyor')
  tl.to(anim, { reactor: 1.8, duration: 0.1, ease: 'power4.out' }, 0.45)
    .to(anim, { reactor: 0.3, duration: 0.08 }, 0.55)
    .to(anim, { reactor: 1, duration: 0.35, ease: 'power2.inOut' }, 0.63)
  tl.to(anim, { arcs: 1, duration: 0.08 }, 0.45).to(anim, { arcs: 0, duration: 0.45, ease: 'power1.in' }, 0.6)
  stage(0.9, 'reactor', 'hazir')

  // --- tarama halkasi + parcaciklar
  tl.to(anim, { scan: 1, duration: 0.25 }, BUILD_START - 0.15)
  tl.fromTo(anim, { particles: 0 }, { particles: 1.15, duration: BUILD_END - BUILD_START + 0.5, ease: 'none' }, BUILD_START - 0.4)
  tl.fromTo(anim, { glb: 0 }, { glb: 1, duration: BUILD_END - BUILD_START, ease: 'power1.inOut' }, BUILD_START)

  // --- parcalar sirayla
  tl.set(anim, { scanY: 1.4 }, 0)
  for (const [group, at, scanTo] of ORDER) {
    tl.to(anim.holo, { [group]: 1, duration: LINES_TIME, ease: 'power1.out' }, at - LINES_LEAD)
    tl.to(anim.solid, { [group]: 1, duration: SHELL_TIME, ease: 'power1.inOut' }, at)
    tl.to(anim, { scanY: scanTo, duration: SHELL_TIME * 0.9, ease: 'power1.inOut' }, at)
  }
  // tarama halkasi bolge degistirirken siçrar (bacaklardan omuzlara, kollardan boyuna)
  tl.set(anim, { scanY: 1.5 }, 2.78)
  tl.set(anim, { scanY: 1.56 }, 3.93)

  stage(0.95, 'torso', 'kuruluyor')
  say(1.0, 'Gövde biçimlendiriliyor')
  stage(1.72, 'torso', 'hazir')
  stage(1.72, 'legs', 'kuruluyor')
  say(1.75, 'Bacaklar · itici yuvaları')
  stage(2.8, 'legs', 'hazir')
  stage(2.8, 'arms', 'kuruluyor')
  say(2.85, 'Kollar · repulsör kanalları')
  stage(3.95, 'arms', 'hazir')
  stage(3.95, 'helmet', 'kuruluyor')
  say(4.0, 'Kask · optik hizalama')

  // --- 360 derece donus + sinematik yaklasma
  tl.fromTo(anim, { spin: 0 }, { spin: Math.PI * 2, duration: BOOT_SECONDS - 1.1, ease: 'power2.inOut' }, 0.9)
  tl.fromTo(anim, { dolly: 0 }, { dolly: 1, duration: BOOT_SECONDS - 0.5, ease: 'power2.inOut' }, 0.4)

  // --- guc gostergesi
  const power = { v: 0 }
  tl.to(power, { v: 100, duration: BUILD_END - 0.45, ease: 'power1.inOut', onUpdate: () => hud.set({ power: Math.round(power.v) }) }, 0.45)

  // --- gozler ve iticiler
  tl.to(anim, { eyes: 1.7, duration: 0.07, ease: 'power4.out' }, 4.85).to(anim, { eyes: 1, duration: 0.25 }, 4.92)
  stage(4.9, 'helmet', 'hazir')
  tl.to(anim, { repulsors: 2, duration: 0.2, ease: 'power3.out' }, 5.0).to(anim, { repulsors: 1, duration: 0.4, ease: 'power2.inOut' }, 5.2)
  tl.to(anim, { scan: 0, duration: 0.4 }, BUILD_END)

  tl.call(
    () => {
      hud.log('Tüm sistemler çevrimiçi')
      hud.set({ phase: 'idle', power: 100 })
      onIdle()
    },
    undefined,
    BOOT_SECONDS,
  )
  return tl
}
