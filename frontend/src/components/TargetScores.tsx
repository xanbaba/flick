import { useEffect, useRef } from 'react'

import type { Streams } from '../lib/streams'
import type { SysStatusPayload } from '../lib/types'

export function TargetScores({
  streams,
  labels,
  frequencies,
  cancelIdx,
  decision,
}: {
  streams: React.MutableRefObject<Streams>
  labels: string[]
  frequencies: number[]
  cancelIdx: number
  decision?: SysStatusPayload['decision']
}) {
  const root = useRef<HTMLDivElement>(null)
  const count = Math.max(labels.length, frequencies.length, cancelIdx + 1)
  const threshold = decision?.rho_threshold
  const dwell = decision?.dwell_windows

  useEffect(() => {
    const node = root.current
    if (!node) return
    let raf = 0
    const tick = () => {
      const scores = streams.current.scores
      const rows = node.querySelectorAll<HTMLElement>('[data-row]')
      rows.forEach((row, i) => {
        const rho = scores?.rho[i] ?? 0
        const bar = row.querySelector<HTMLElement>('[data-bar]')
        const val = row.querySelector<HTMLElement>('[data-val]')
        if (bar) {
          const width = Math.max(0, Math.min(100, rho * 100))
          bar.style.width = `${width}%`
          const hot = Boolean(scores && scores.winner_idx === i && scores.above_threshold)
          bar.style.background = hot ? 'oklch(0.87 0.17 158)' : 'oklch(0.45 0.02 160)'
        }
        if (val) val.textContent = scores ? rho.toFixed(2) : '—'
        const pips = row.querySelectorAll<HTMLElement>('[data-pip]')
        const filled = scores && scores.winner_idx === i ? scores.dwell_count : 0
        pips.forEach((pip, p) => {
          pip.style.background = p < filled ? 'oklch(0.87 0.17 158)' : 'transparent'
        })
      })
      const margin = node.querySelector<HTMLElement>('[data-margin]')
      const chip = node.querySelector<HTMLElement>('[data-chip]')
      if (margin) margin.textContent = scores ? `margin ${scores.margin.toFixed(2)}` : ''
      if (chip) {
        if (!scores) chip.textContent = 'WAITING'
        else if (scores.above_threshold) chip.textContent = `DWELL ${scores.dwell_count}/${dwell ?? '?'}`
        else chip.textContent = 'BELOW'
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [streams, count, dwell])

  const rows = Array.from({ length: count }, (_, i) => {
    const label = labels[i] ?? `target ${i + 1}`
    const freq = frequencies[i]
    return { i, label, freq: freq != null ? `${freq.toFixed(1)} Hz` : '—', cancel: i === cancelIdx }
  })

  return (
    <div
      ref={root}
      className="flex flex-col gap-2.5 rounded-[10px] border border-line bg-panel px-4 py-3"
    >
      <div className="flex items-center gap-2.5">
        <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Target scores · ρ</span>
        <span className="font-mono text-[10.5px] text-[oklch(0.9_0.16_100)]">threshold {threshold?.toFixed(2) ?? '—'}</span>
        <span className="flex-1" />
        <span data-margin="" className="font-mono text-[10.5px] text-muted" />
        <span data-chip="" className="max-w-[55%] truncate rounded-[5px] bg-[oklch(0.25_0.01_160)] px-2 py-0.5 font-mono text-[10.5px] font-semibold tracking-wide text-[oklch(0.76_0.012_160)]">
          WAITING
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <div
            key={row.i}
            data-row=""
            className="grid grid-cols-[minmax(0,1.3fr)_54px_minmax(0,2fr)_36px_34px] items-center gap-2.5"
          >
            <span className={`truncate text-[13px] ${row.cancel ? 'text-[oklch(0.9_0.16_100)]' : 'text-ink'}`}>
              {row.label}
            </span>
            <span className="text-right font-mono text-[11px] text-[oklch(0.76_0.012_160)]">{row.freq}</span>
            <div className="relative h-3 rounded-[3px] bg-[oklch(0.23_0.01_160)]">
              <div data-bar="" className="absolute inset-y-0 left-0 w-0 rounded-[3px] bg-[oklch(0.45_0.02_160)]" />
              {threshold != null && <div
                className="absolute -bottom-1 -top-1 border-l-[1.5px] border-dashed border-[oklch(0.9_0.16_100/0.9)]"
                style={{ left: `${threshold * 100}%` }}
              />}
            </div>
            <span data-val="" className="text-right font-mono text-[11px] tabular-nums text-[oklch(0.76_0.012_160)]">
              —
            </span>
            <span className="flex gap-[3px]">
              {Array.from({ length: dwell ?? 0 }, (_, p) => (
                <span
                  key={p}
                  data-pip=""
                  className="h-2 w-2 rounded-full border border-accent/50"
                />
              ))}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
