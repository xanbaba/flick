import { useEffect, useRef } from 'react'

import { CHANNEL_COLORS, CHANNELS } from '../lib/color'
import { EegTrace } from '../lib/plots'
import type { Streams } from '../lib/streams'

export function EegTraceView({ streams }: { streams: React.MutableRefObject<Streams> }) {
  const plotEl = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = plotEl.current
    if (!el) return
    const plot = new EegTrace(el, CHANNELS.length, CHANNEL_COLORS, 'rgba(255,255,255,0.06)')
    let raf = 0
    const tick = (now: number) => {
      const frame = streams.current.eeg
      if (frame && frame !== streams.current.eegDrawn) {
        streams.current.eegDrawn = frame
        plot.push(frame.data, frame.fs)
      }
      plot.frame(now)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      plot.destroy()
    }
  }, [streams])

  return (
    <section className="flex flex-col gap-2 rounded-[10px] border border-line bg-panel px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">EEG · 8 channels · 4 s</span>
        <span className="flex-1" />
        <span className="inline-flex items-center gap-2 font-mono text-[10.5px] text-[oklch(0.76_0.012_160)]">
          <span className="h-3.5 w-0.5 bg-[oklch(0.76_0.012_160)]" />
          20 µV
        </span>
      </div>
      <div className="grid h-[208px] grid-cols-[40px_minmax(0,1fr)] gap-2.5">
        <div className="grid grid-rows-8 items-center font-mono text-[10.5px]">
          {CHANNELS.map((name, i) => (
            <span key={name} style={{ color: CHANNEL_COLORS[i] }}>
              {name}
            </span>
          ))}
        </div>
        <div className="relative min-w-0">
          <div ref={plotEl} className="absolute inset-0" />
        </div>
      </div>
      <div className="grid grid-cols-[40px_minmax(0,1fr)] gap-2.5 font-mono text-[10px] text-muted">
        <span />
        <div className="flex justify-between">
          <span>−4 s</span>
          <span>−3 s</span>
          <span>−2 s</span>
          <span>−1 s</span>
          <span>now</span>
        </div>
      </div>
    </section>
  )
}
