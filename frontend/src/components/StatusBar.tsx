import { useEffect, useState } from 'react'

import type { ConnState } from '../lib/ws'
import type { SysStatusPayload } from '../lib/types'

function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function providerRows(providers: Record<string, Record<string, boolean>>) {
  return (['llm', 'stt', 'tts'] as const).map((slot) => {
    const links = providers[slot] ?? {}
    const healthy = Object.entries(links).find(([, ok]) => ok)
    return {
      slot: slot.toUpperCase(),
      name: healthy?.[0] ?? Object.keys(links)[0] ?? '—',
      ok: Boolean(healthy),
    }
  })
}

export function StatusBar({ conn, status }: { conn: ConnState; status: SysStatusPayload | null }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(id)
  }, [])

  const integrity = status?.stimulus_integrity
  const drops = integrity ? `${integrity.dropped_frames_last_s} drops` : '— drops'
  const hz =
    status?.measured_refresh_hz != null ? `${status.measured_refresh_hz.toFixed(1)} Hz` : '— Hz'
  const providers = providerRows(status?.providers ?? {})

  return (
    <header className="sticky top-0 z-40 flex min-h-[54px] flex-wrap items-center gap-x-5 gap-y-2 border-b border-line bg-[oklch(0.135_0.008_160)] px-4 py-2 font-mono text-[11px] text-[oklch(0.76_0.012_160)]">
      <div className="flex items-baseline gap-2.5">
        <span className="font-sans text-[21px] font-bold tracking-tight text-ink">flick</span>
        <span className="tabular-nums text-muted">{formatClock(elapsed)}</span>
      </div>
      {conn.state === 'live' && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/15 px-2.5 py-1 font-semibold tracking-wider text-accent">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          LIVE
        </span>
      )}
      {conn.state !== 'live' && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[oklch(0.7_0.19_25/0.16)] px-2.5 py-1 font-semibold tracking-wider text-[oklch(0.78_0.16_30)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[oklch(0.78_0.16_30)]" />
          {conn.state === 'connecting' ? 'CONNECTING' : `RETRY ${Math.round(conn.retryMs)}ms`}
        </span>
      )}
      <span className="inline-flex items-center gap-2">
        <span className="text-muted">STIM</span>
        <span className="text-ink">{status?.profile ?? '—'}</span>
        <span className="text-ink">{hz}</span>
        <span className="text-[oklch(0.45_0.01_160)]">/</span>
        <span>{drops}</span>
      </span>
      <span className="inline-flex items-center gap-2">
        <span className="text-muted">EEG</span>
        <span className="text-ink">{status?.source ?? '—'}</span>
      </span>
      <span className="inline-flex items-center gap-3.5">
        {providers.map((p) => (
          <span key={p.slot} className="inline-flex items-center gap-1.5">
            <span className="text-muted">{p.slot}</span>
            <span className={`h-1.5 w-1.5 rounded-full ${p.ok ? 'bg-accent' : 'bg-[oklch(0.45_0.01_160)]'}`} />
            <span className="text-ink">{p.name}</span>
          </span>
        ))}
      </span>
      <span className="inline-flex items-center gap-2">
        <span className="text-muted">TEL</span>
        <span>{status ? status.telemetry_dropped : '—'}</span>
      </span>
      <span className="flex-1" />
      {status?.local_mode && (
        <span className="rounded-md bg-accent px-3 py-1.5 font-bold tracking-widest text-[oklch(0.17_0.03_158)]">
          LOCAL MODE
        </span>
      )}
      {status?.input_badge && (
        <span
          role="status"
          className="rounded-md bg-badge px-3.5 py-2 text-[12.5px] font-bold tracking-wide text-[oklch(0.14_0.02_100)] shadow-[0_0_0_2px_oklch(0.14_0.02_100),0_0_0_3.5px_oklch(0.9_0.18_100)]"
        >
          {status.input_badge}
        </span>
      )}
    </header>
  )
}
