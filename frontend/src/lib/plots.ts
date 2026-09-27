import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { oklchToRgb } from './color'

const FONT = '10px "Martian Mono", monospace'

export class EegTrace {
  private readonly u: uPlot
  private readonly ro: ResizeObserver
  private readonly ys: number[][]
  private xs: number[] = []
  private fs = 250
  private total = 0
  private play: number | null = null
  private last = performance.now()
  private dirty = false
  private min: number
  private max = 0

  constructor(
    el: HTMLElement,
    private readonly n: number,
    colors: string[],
    private readonly grid: string,
    private readonly win = 4,
    private readonly sp = 36,
  ) {
    this.min = -win
    this.ys = Array.from({ length: n }, () => [])
    const series: uPlot.Series[] = [
      {},
      ...colors.slice(0, n).map((stroke) => ({ stroke, width: 1.1, points: { show: false } })),
    ]
    this.u = new uPlot(
      {
        width: Math.max(10, el.clientWidth),
        height: Math.max(10, el.clientHeight),
        pxAlign: 0,
        cursor: { show: false },
        legend: { show: false },
        select: { show: false, left: 0, top: 0, width: 0, height: 0 },
        padding: [0, 0, 0, 0],
        scales: {
          x: { time: false, range: () => [this.min, this.max] },
          y: { range: () => [-(this.n - 0.5) * this.sp, 0.5 * this.sp] },
        },
        axes: [{ show: false }, { show: false }],
        series,
        hooks: { drawClear: [() => this.drawGrid()] },
      },
      [[], ...this.ys],
      el,
    )
    this.ro = new ResizeObserver(() =>
      this.u.setSize({ width: Math.max(10, el.clientWidth), height: Math.max(10, el.clientHeight) }),
    )
    this.ro.observe(el)
  }

  push(data: number[][], fs: number): void {
    this.fs = fs || 250
    const samples = data[0]?.length ?? 0
    const cap = Math.round(this.fs * (this.win + 1.5))
    const lim = this.sp * 0.95
    for (let i = 0; i < samples; i++) this.xs.push((this.total + i) / this.fs)
    for (let k = 0; k < this.n; k++) {
      const col = data[k] ?? []
      const ys = this.ys[k]
      for (let i = 0; i < samples; i++) ys.push(Math.max(-lim, Math.min(lim, col[i] || 0)) - k * this.sp)
    }
    this.total += samples
    if (this.xs.length > cap + 250) {
      const cut = this.xs.length - cap
      this.xs.splice(0, cut)
      this.ys.forEach((y) => y.splice(0, cut))
    }
    this.dirty = true
  }

  frame(now: number): void {
    const dt = Math.min(0.1, (now - this.last) / 1000)
    this.last = now
    if (!this.total) return
    const head = this.total / this.fs
    const target = head - 0.3
    if (this.play == null || Math.abs(target - this.play) > 1.5) this.play = target
    this.play += dt + (target - this.play) * 0.06
    if (this.play > head) this.play = head
    this.min = this.play - this.win
    this.max = this.play
    if (this.dirty) {
      this.u.setData([this.xs, ...this.ys], false)
      this.dirty = false
    }
    this.u.setScale('x', { min: this.min, max: this.max })
  }

  private drawGrid(): void {
    const { ctx } = this.u
    const bbox = this.u.bbox
    ctx.save()
    ctx.strokeStyle = this.grid
    ctx.lineWidth = 1
    for (let s = Math.ceil(this.min); s <= this.max; s++) {
      const x = Math.round(this.u.valToPos(s, 'x', true)) + 0.5
      ctx.beginPath()
      ctx.moveTo(x, bbox.top)
      ctx.lineTo(x, bbox.top + bbox.height)
      ctx.stroke()
    }
    ctx.restore()
  }

  destroy(): void {
    this.ro.disconnect()
    this.u.destroy()
  }
}

export class PsdPlot {
  private readonly u: uPlot
  private readonly ro: ResizeObserver
  private readonly lut = buildLut()
  private freqs: number[] | null = null
  private disp: number[] | null = null
  private target: number[] | null = null
  private fresh = false
  private targets: number[] = []
  private cancelIdx = -1
  private winner = -1
  private hot = false
  private yLo = -15
  private yHi = 20
  private cLo = -10
  private cHi = 15

  constructor(
    el: HTMLElement,
    private readonly wf: HTMLCanvasElement,
    private readonly colors: { accent: string; text: string; muted: string; grid: string; fill: string },
  ) {
    this.u = new uPlot(
      {
        width: Math.max(10, el.clientWidth),
        height: Math.max(10, el.clientHeight),
        pxAlign: 0,
        cursor: { show: false },
        legend: { show: false },
        select: { show: false, left: 0, top: 0, width: 0, height: 0 },
        padding: [14, 6, 0, 6],
        scales: {
          x: { time: false, range: [0, 48] },
          y: { range: () => [this.yLo, this.yHi] },
        },
        axes: [
          {
            stroke: colors.muted,
            font: FONT,
            size: 20,
            gap: 3,
            grid: { show: false },
            ticks: { stroke: colors.grid, size: 3 },
            splits: () => [0, 6, 12, 18, 24, 30, 36, 42, 48],
            values: (_u, v) => v.map((x) => (x === 48 ? '48 Hz' : String(x))),
          },
          { show: false },
        ],
        series: [
          {},
          {
            stroke: colors.accent,
            width: 1.6,
            fill: colors.fill,
            fillTo: (u) => u.scales.y.min ?? 0,
            points: { show: false },
          },
        ],
        hooks: { drawClear: [() => this.under()], draw: [() => this.over()] },
      },
      [
        [0, 48],
        [0, 0],
      ],
      el,
    )
    this.ro = new ResizeObserver(() =>
      this.u.setSize({ width: Math.max(10, el.clientWidth), height: Math.max(10, el.clientHeight) }),
    )
    this.ro.observe(el)
  }

  setTargets(freqs: number[], cancelIdx: number): void {
    this.targets = freqs
    this.cancelIdx = cancelIdx
  }

  setWinner(idx: number, hot: boolean): void {
    this.winner = idx
    this.hot = hot
  }

  push(freqs: number[], power: number[]): void {
    this.freqs = freqs
    this.target = power
    if (!this.disp || this.disp.length !== power.length) this.disp = power.slice()
    const band = power.filter((_, i) => freqs[i] >= 4)
    if (band.length) {
      const lo = Math.min(...band)
      const hi = Math.max(...band)
      this.yLo += (lo - 4 - this.yLo) * 0.15
      this.yHi += (hi + 5 - this.yHi) * 0.15
      this.cLo += (lo - this.cLo) * 0.1
      this.cHi += (hi - this.cHi) * 0.1
    }
    this.fresh = true
  }

  readout(): { label: string; snr: number } | null {
    if (!this.target || !this.freqs || !this.targets.length) return null
    const band = this.target
      .filter((_, i) => this.freqs![i] >= 5 && this.freqs![i] <= 45)
      .slice()
      .sort((a, b) => a - b)
    const median = band[Math.floor(band.length / 2)] ?? 0
    const at = (f: number) => (this.target![Math.round(f * 2)] ?? median) - median
    return this.hot && this.winner >= 0
      ? { label: `${this.targets[this.winner].toFixed(1)} Hz`, snr: at(this.targets[this.winner]) }
      : { label: 'α 10 Hz', snr: at(10) }
  }

  frame(): void {
    if (!this.disp || !this.target || !this.freqs) return
    for (let i = 0; i < this.disp.length; i++) this.disp[i] += (this.target[i] - this.disp[i]) * 0.3
    this.u.batch(() => {
      this.u.setData([this.freqs!, this.disp!], false)
      this.u.setScale('x', { min: 0, max: 48 })
      this.u.setScale('y', { min: this.yLo, max: this.yHi })
    })
    if (this.fresh) {
      this.fresh = false
      this.row()
    }
  }

  private under(): void {
    const { ctx } = this.u
    const bbox = this.u.bbox
    const x0 = this.u.valToPos(8, 'x', true)
    const x1 = this.u.valToPos(12, 'x', true)
    ctx.save()
    ctx.fillStyle = 'rgba(255,255,255,0.035)'
    ctx.fillRect(x0, bbox.top, x1 - x0, bbox.height)
    ctx.fillStyle = this.colors.muted
    ctx.font = `${10 * devicePixelRatio}px "Martian Mono", monospace`
    ctx.textAlign = 'center'
    ctx.fillText('α', (x0 + x1) / 2, bbox.top + bbox.height - 6 * devicePixelRatio)
    ctx.restore()
  }

  private over(): void {
    const { ctx } = this.u
    const bbox = this.u.bbox
    const dpr = devicePixelRatio
    ctx.save()
    ctx.font = `${10 * dpr}px "Martian Mono", monospace`
    ctx.textAlign = 'center'
    this.targets.forEach((f, i) => {
      const x = Math.round(this.u.valToPos(f, 'x', true)) + 0.5
      const win = i === this.winner && this.hot
      ctx.strokeStyle = win ? this.colors.accent : this.colors.grid
      ctx.lineWidth = win ? 1.5 * dpr : dpr
      ctx.setLineDash(win ? [] : [3 * dpr, 3 * dpr])
      ctx.beginPath()
      ctx.moveTo(x, bbox.top)
      ctx.lineTo(x, bbox.top + bbox.height)
      ctx.stroke()
      ctx.fillStyle = win ? this.colors.accent : this.colors.muted
      ctx.fillText(i === this.cancelIdx ? '✕' : String(i + 1), x, bbox.top - 3 * dpr)
    })
    ctx.restore()
  }

  private row(): void {
    const cv = this.wf
    if (!this.freqs || !this.target) return
    const dpr = devicePixelRatio
    const left = this.u.bbox.left / dpr
    const width = this.u.bbox.width / dpr
    cv.style.left = `${left}px`
    cv.style.width = `${width}px`
    const W = Math.max(8, Math.round(width * dpr))
    const H = Math.max(8, Math.round(cv.clientHeight * dpr))
    if (cv.width !== W || cv.height !== H) {
      cv.width = W
      cv.height = H
    }
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const rowH = Math.max(1, Math.round(dpr))
    ctx.drawImage(cv, 0, rowH)
    const img = ctx.createImageData(W, rowH)
    const span = Math.max(1, this.cHi - this.cLo + 4)
    for (let x = 0; x < W; x++) {
      const k = (x / (W - 1)) * 96
      const k0 = Math.floor(k)
      const fr = k - k0
      const p = this.target[k0] * (1 - fr) + (this.target[Math.min(96, k0 + 1)] ?? this.target[k0]) * fr
      const t = Math.max(0, Math.min(1, (p - this.cLo + 2) / span)) ** 1.6
      const c = this.lut[Math.round(t * 255)]
      for (let y = 0; y < rowH; y++) {
        const o = (y * W + x) * 4
        img.data[o] = c[0]
        img.data[o + 1] = c[1]
        img.data[o + 2] = c[2]
        img.data[o + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }

  destroy(): void {
    this.ro.disconnect()
    this.u.destroy()
  }
}

function buildLut(): [number, number, number][] {
  const stops: [number, number, number][] = [
    [0.16, 0.01, 160],
    [0.36, 0.08, 175],
    [0.62, 0.15, 160],
    [0.87, 0.17, 158],
    [0.98, 0.04, 120],
  ]
  return Array.from({ length: 256 }, (_, i) => {
    const t = (i / 255) * (stops.length - 1)
    const j = Math.min(stops.length - 2, Math.floor(t))
    const f = t - j
    const a = stops[j]
    const b = stops[j + 1]
    return oklchToRgb(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
  })
}
