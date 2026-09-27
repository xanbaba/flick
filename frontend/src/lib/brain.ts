import ForceGraph3D, { type ForceGraph3DInstance } from '3d-force-graph'
import { Color, Mesh, MeshLambertMaterial, SphereGeometry, Vector2 } from 'three'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'

import type { GraphEdge, GraphNode } from './types'
import { ACCENT_HEX, KIND_HEX } from './color'

interface Fx {
  bloom?: number | null
  pulse?: number | null
  glow?: number | null
  born?: number | null
}

interface BrainNode extends GraphNode {
  x?: number
  y?: number
  z?: number
  __r?: number
  __m?: Mesh
  __base?: Color
}

interface BrainLink extends Omit<GraphEdge, 'source' | 'target'> {
  source: string | BrainNode
  target: string | BrainNode
}

type Graph = ForceGraph3DInstance<BrainNode, BrainLink> & {
  d3Force(name: string): { strength(n: number): void; distance(fn: (l: BrainLink) => number): void } | undefined
  emitParticle(link: BrainLink): void
  onEngineStop(cb: () => void): Graph
}

const easeOutBack = (t: number) => 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2
const jitter = (s: number) => (Math.random() - 0.5) * s
const esc = (s: string) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)

function endId(end: string | BrainNode): string {
  return typeof end === 'string' ? end : end.id
}

export class MemoryBrain {
  private readonly nodes = new Map<string, BrainNode>()
  private readonly links = new Map<string, BrainLink>()
  private readonly fx = new Map<string, Fx>()
  private readonly g: Graph
  private readonly accent = new Color(ACCENT_HEX)
  private readonly geo: SphereGeometry
  private readonly labelLayer: HTMLDivElement
  private readonly labelPool: HTMLDivElement[] = []
  private readonly ro: ResizeObserver
  private touched = 0
  private raf = 0
  private fitTimer: ReturnType<typeof setTimeout> | null = null

  static async create(el: HTMLElement): Promise<MemoryBrain> {
    return new MemoryBrain(el)
  }

  constructor(private readonly el: HTMLElement) {
    this.geo = new SphereGeometry(1, 20, 14)
    const host = document.createElement('div')
    host.style.cssText = 'position:absolute;inset:0;'
    this.labelLayer = document.createElement('div')
    this.labelLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;'
    el.append(host, this.labelLayer)

    const g = new ForceGraph3D(host, { controlType: 'orbit' }) as unknown as Graph
    g.width(el.clientWidth)
      .height(el.clientHeight)
      .backgroundColor('#0b100e')
      .showNavInfo(false)
      .nodeThreeObject((n) => this.makeNode(n))
      .nodeLabel(
        (n) =>
          `<div style="font:500 12px 'Hanken Grotesk',sans-serif;padding:6px 9px;border-radius:6px;background:rgba(12,18,16,.92);border:1px solid rgba(255,255,255,.12);color:#e8f0ec"><span style="color:${KIND_HEX[n.kind] || '#ccc'};font:10px 'Martian Mono',monospace;letter-spacing:.06em;text-transform:uppercase">${esc(n.kind)}</span><br>${esc(n.label)}</div>`,
      )
      .linkColor(() => 'rgba(185,225,205,1)')
      .linkOpacity(0.22)
      .linkWidth(0)
      .linkDirectionalParticles(0)
      .linkDirectionalParticleWidth(2.6)
      .linkDirectionalParticleSpeed(0.028)
      .linkDirectionalParticleColor(() => ACCENT_HEX)
      .d3AlphaDecay(0.018)
      .d3VelocityDecay(0.32)
      .cooldownTime(25000)
      .graphData({ nodes: [], links: [] })
    g.d3Force('charge')?.strength(-38)
    g.d3Force('link')?.distance((l: BrainLink) => (l.kind === 'INVOLVES' ? 26 : 34))
    try {
      const bp = new UnrealBloomPass(new Vector2(el.clientWidth, el.clientHeight), 1.4, 0.6, 0.16)
      g.postProcessingComposer().addPass(bp)
    } catch (err) {
      console.warn('MemoryBrain: bloom pass unavailable', err)
    }
    const controls = g.controls() as {
      autoRotate: boolean
      autoRotateSpeed: number
      addEventListener: (ev: string, fn: () => void) => void
    }
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.5
    controls.addEventListener('start', () => {
      this.touched = performance.now()
    })
    g.onEngineStop(() => this.fit(900))
    g.cameraPosition({ x: 0, y: 40, z: 300 })
    this.g = g
    this.ro = new ResizeObserver(() => g.width(el.clientWidth).height(el.clientHeight))
    this.ro.observe(el)
    this.raf = requestAnimationFrame(() => this.tick())
  }

  private radius(w: number): number {
    return 3 + 2.4 * Math.sqrt(Math.max(0.2, w || 1))
  }

  private makeNode(n: BrainNode): Mesh {
    const base = new Color(KIND_HEX[n.kind] || '#cccccc')
    const mat = new MeshLambertMaterial({
      color: base,
      emissive: base.clone(),
      emissiveIntensity: 0.34,
      transparent: true,
      opacity: 0.95,
    })
    const m = new Mesh(this.geo, mat)
    n.__r = this.radius(n.weight)
    n.__m = m
    n.__base = base
    const f = this.fx.get(n.id)
    m.scale.setScalar(f && f.bloom != null ? 0.001 : n.__r)
    return m
  }

  private fxSet(id: string, key: keyof Fx, t: number): void {
    const f = this.fx.get(id) ?? {}
    f[key] = t
    this.fx.set(id, f)
  }

  private tick(): void {
    const now = performance.now()
    for (const [id, f] of this.fx) {
      const n = this.nodes.get(id)
      if (!n?.__m || !n.__base) continue
      let s = 1
      let glow = 0
      let live = false
      if (f.bloom != null) {
        const t = (now - f.bloom) / 500
        if (t < 1) {
          s = t <= 0 ? 0.001 : Math.max(0.001, easeOutBack(t))
          glow = Math.max(glow, 0.8 * (1 - Math.max(0, t)))
          live = true
        } else {
          f.bloom = null
          f.born = now
        }
      }
      if (f.pulse != null) {
        const t = (now - f.pulse) / 600
        if (t < 0) live = true
        else if (t < 1) {
          s *= 1 + 0.75 * Math.sin(Math.PI * t)
          glow = Math.max(glow, 1 - t)
          live = true
        } else f.pulse = null
      }
      if (f.glow != null) {
        const t = now - f.glow
        const e = t < 3000 ? 1 : Math.exp(-(t - 3000) / 500)
        if (e > 0.02) {
          glow = Math.max(glow, e)
          live = true
        } else f.glow = null
      }
      if (f.born != null) {
        if (now - f.born < 4000) live = true
        else f.born = null
      }
      n.__m.scale.setScalar(Math.max(0.001, (n.__r ?? 3) * s))
      const mat = n.__m.material as MeshLambertMaterial
      if (glow > 0.01) {
        mat.emissive.copy(n.__base).lerp(this.accent, Math.min(1, glow))
        mat.emissiveIntensity = 0.3 + 1.7 * glow
      } else {
        mat.emissive.copy(n.__base)
        mat.emissiveIntensity = 0.34
      }
      if (!live) this.fx.delete(id)
    }
    this.drawLabels()
    this.raf = requestAnimationFrame(() => this.tick())
  }

  private drawLabels(): void {
    const picks: [number, BrainNode][] = []
    for (const [id, f] of this.fx) {
      const n = this.nodes.get(id)
      if (!n) continue
      const pr = f.glow != null ? 3 : f.bloom != null || f.born != null ? 2 : f.pulse != null ? 1 : 0
      if (pr) picks.push([pr, n])
    }
    picks.sort((a, b) => b[0] - a[0])
    const chosen: { n: BrainNode; hot: boolean }[] = picks.slice(0, 12).map((p) => ({ n: p[1], hot: true }))
    const have = new Set(chosen.map((c) => c.n.id))
    for (const n of this.nodes.values()) {
      if (n.kind === 'Person' && !have.has(n.id) && chosen.length < 18) chosen.push({ n, hot: false })
    }
    const W = this.el.clientWidth
    const H = this.el.clientHeight
    const boxes: [number, number, number][] = []
    let used = 0
    for (const c of chosen) {
      const { n } = c
      if (n.x == null || n.y == null || n.z == null) continue
      const p = this.g.graph2ScreenCoords(n.x, n.y, n.z)
      const x = p.x + (n.__r || 3) + 5
      const y = p.y - 9
      const w = n.label.length * 6.3 + 14
      if (p.x < -50 || p.y < -20 || p.x > W + 50 || p.y > H + 20) continue
      if (boxes.some((b) => x < b[0] + b[2] && x + w > b[0] && y < b[1] + 19 && y + 19 > b[1])) continue
      boxes.push([x, y, w])
      let d = this.labelPool[used]
      if (!d) {
        d = document.createElement('div')
        d.style.cssText =
          "position:absolute;left:0;top:0;white-space:nowrap;font:500 11px 'Hanken Grotesk',sans-serif;padding:2px 7px;border-radius:4px;"
        this.labelLayer.appendChild(d)
        this.labelPool[used] = d
      }
      used++
      if (d.textContent !== n.label) d.textContent = n.label
      d.style.display = 'block'
      d.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`
      d.style.color = c.hot ? '#eafff4' : 'rgba(225,238,231,.72)'
      d.style.background = c.hot ? 'rgba(10,30,22,.8)' : 'transparent'
      d.style.boxShadow = c.hot ? `inset 0 0 0 1px ${ACCENT_HEX}66` : 'none'
    }
    for (let i = used; i < this.labelPool.length; i++) this.labelPool[i].style.display = 'none'
  }

  private fit(ms: number): void {
    if (!this.touched || performance.now() - this.touched > 10000) this.g.zoomToFit(ms, 30)
  }

  setSnapshot(snapshot: { nodes?: GraphNode[]; edges?: GraphEdge[] }): void {
    const nodes = snapshot.nodes ?? []
    const edges = snapshot.edges ?? []
    if (!nodes.length) {
      this.nodes.clear()
      this.links.clear()
      this.fx.clear()
      this.g.graphData({ nodes: [], links: [] })
      return
    }
    if (!this.nodes.size) {
      this.bloom({ nodes, edges }, 5)
      return
    }
    const keep = new Set(nodes.map((n) => n.id))
    for (const id of [...this.nodes.keys()]) if (!keep.has(id)) this.nodes.delete(id)
    for (const [id, l] of [...this.links]) {
      if (!this.nodes.has(endId(l.source)) || !this.nodes.has(endId(l.target))) this.links.delete(id)
    }
    const { nodes: curN } = this.g.graphData()
    this.g.graphData({ nodes: curN.filter((n) => keep.has(n.id)), links: [...this.links.values()] })
    this.bloom({ nodes, edges }, 5, true)
  }

  bloom(batch: { nodes?: GraphNode[]; edges?: GraphEdge[] }, stagger = 35, quiet = false): void {
    const nodes = batch.nodes ?? []
    const edges = batch.edges ?? []
    const now = performance.now()
    const cur = this.g.graphData()
    const addN: BrainNode[] = []
    const addL: BrainLink[] = []
    let i = 0
    for (const raw of nodes) {
      const ex = this.nodes.get(raw.id)
      if (ex) {
        if (raw.weight !== ex.weight) {
          ex.weight = raw.weight
          ex.__r = this.radius(raw.weight)
        }
        if (!quiet) this.fxSet(raw.id, 'pulse', now)
        continue
      }
      const n: BrainNode = { ...raw }
      const edge = edges.find(
        (e) => (e.source === n.id && this.nodes.has(e.target)) || (e.target === n.id && this.nodes.has(e.source)),
      )
      const parent = edge && this.nodes.get(edge.source === n.id ? edge.target : edge.source)
      if (parent && parent.x != null && parent.y != null && parent.z != null) {
        n.x = parent.x + jitter(14)
        n.y = parent.y + jitter(14)
        n.z = parent.z + jitter(14)
      }
      this.nodes.set(n.id, n)
      addN.push(n)
      this.fxSet(n.id, 'bloom', now + i++ * stagger)
    }
    for (const raw of edges) {
      if (this.links.has(raw.id) || !this.nodes.has(raw.source) || !this.nodes.has(raw.target)) continue
      const l: BrainLink = { ...raw }
      this.links.set(l.id, l)
      addL.push(l)
    }
    if (!addN.length && !addL.length) return
    this.g.graphData({ nodes: [...cur.nodes, ...addN], links: [...cur.links, ...addL] })
    if (addL.length <= 40) setTimeout(() => addL.forEach((l) => this.emit(l)), 80)
    if (this.fitTimer) clearTimeout(this.fitTimer)
    this.fitTimer = setTimeout(() => this.fit(1100), 900)
  }

  activate(event: { node_ids?: string[]; edge_ids?: string[] }): void {
    const nodeIds = event.node_ids ?? []
    const edgeIds = event.edge_ids ?? []
    const now = performance.now()
    const set = new Set(nodeIds)
    let ls = edgeIds.map((id) => this.links.get(id)).filter((l): l is BrainLink => Boolean(l))
    if (!ls.length) {
      ls = [...this.links.values()].filter((l) => set.has(endId(l.source)) && set.has(endId(l.target)))
    }
    ls.slice(0, 40).forEach((l, k) => setTimeout(() => this.emit(l), k * 25))
    nodeIds.forEach((id, k) => this.fxSet(id, 'pulse', now + 120 + k * 60))
  }

  glow(ids: string[] = []): void {
    const now = performance.now()
    ids.forEach((id) => {
      if (this.nodes.has(id)) this.fxSet(id, 'glow', now)
    })
  }

  private emit(link: BrainLink): void {
    try {
      this.g.emitParticle(link)
    } catch (err) {
      console.warn('MemoryBrain: emitParticle failed', err)
    }
  }

  nodeCount(): number {
    return this.nodes.size
  }

  destroy(): void {
    cancelAnimationFrame(this.raf)
    this.ro.disconnect()
    try {
      this.g._destructor()
    } catch (err) {
      console.warn('MemoryBrain: destructor failed', err)
    }
  }
}
