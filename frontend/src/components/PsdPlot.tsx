import { useEffect, useRef } from 'react'

import { ACCENT_HEX } from '../lib/color'
import { PsdPlot } from '../lib/plots'
import type { Streams } from '../lib/streams'

export function PsdPlotView({
  streams,
  frequencies,
  cancelIdx,
}: {
  streams: React.MutableRefObject<Streams>
  frequencies: number[]
  cancelIdx: number
}) {
  const plotEl = useRef<HTMLDivElement>(null)
  const wfEl = useRef<HTMLCanvasElement>(null)
  const readoutEl = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = plotEl.current
    const wf = wfEl.current
    if (!el || !wf) return
    const plot = new PsdPlot(el, wf, {
      accent: ACCENT_HEX,
      text: '#e8f0ec',
      muted: 'rgba(180,200,190,0.7)',
      grid: 'rgba(255,255,255,0.18)',
      fill: 'rgba(90, 220, 170, 0.12)',
    })
    let raf = 0
    const tick = () => {
      plot.setTargets(frequencies, cancelIdx)
      const scores = streams.current.scores
      plot.setWinner(scores?.winner_idx ?? -1, Boolean(scores?.above_threshold))
      const frame = streams.current.psd
      if (frame && frame !== streams.current.psdDrawn) {
        streams.current.psdDrawn = frame
        plot.push(frame.freqs, frame.power)
      }
      plot.frame()
      const line = plot.readout()
      if (readoutEl.current) {
        readoutEl.current.textContent = line
          ? `${line.label}  ${line.snr >= 0 ? '+' : ''}${line.snr.toFixed(1)} dB`
          : ''
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      plot.destroy()
    }
  }, [streams, frequencies, cancelIdx])

  return (
    <div className="flex flex-col gap-1.5 rounded-[10px] border border-line bg-panel px-4 py-3">
      <div className="flex items-center gap-2.5">
        <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">PSD · occipital mean</span>
        <span className="flex-1" />
        <span ref={readoutEl} className="font-mono text-[10.5px] text-[oklch(0.76_0.012_160)]" />
      </div>
      <div className="relative h-28">
        <div ref={plotEl} className="absolute inset-0" />
      </div>
      <div className="relative h-[38px]">
        <canvas ref={wfEl} className="absolute left-0 top-0 h-[38px] w-full rounded-[3px] bg-[oklch(0.16_0.01_160)]" />
        <span className="pointer-events-none absolute right-1 top-0 font-mono text-[9.5px] text-muted">now ↑</span>
      </div>
    </div>
  )
}
