import { useState } from 'react'

import { api } from '../lib/api'
import type { WsPayloads } from '../lib/types'

export function PrivacyPanel({
  flows,
  cost,
}: {
  flows: WsPayloads['privacy.flow'][]
  cost: WsPayloads['privacy.cost'] | null
}) {
  const [armed, setArmed] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  async function purge() {
    setNote(null)
    try {
      await api.purge('all')
      setArmed(false)
      setNote('Purge requested.')
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'Purge failed')
    }
  }

  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-[10px] border border-line bg-panel px-4 py-3.5">
      <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Privacy</span>
      <div className="font-mono text-[12px] text-[oklch(0.76_0.012_160)]">
        <div>turn ${cost ? cost.turn_usd.toFixed(4) : '0.0000'}</div>
        <div>session ${cost ? cost.session_usd.toFixed(4) : '0.0000'}</div>
      </div>
      <ul className="flex max-h-36 flex-col gap-1 overflow-auto text-[12.5px]">
        {flows.length === 0 && <li className="text-muted">No outbound activity recorded.</li>}
        {flows.map((flow, i) => (
          <li key={`${flow.destination}-${i}`}>
            <span className="text-accent">{flow.destination}</span>
            <span className="text-muted"> · {flow.bytes} B · {flow.description}</span>
          </li>
        ))}
      </ul>
      {!armed ? (
        <button type="button" onClick={() => setArmed(true)} className="h-8 rounded-md border border-line text-[13px]">
          Purge stored data
        </button>
      ) : (
        <div className="flex gap-2">
          <button type="button" onClick={() => void purge()} className="h-8 flex-1 rounded-md bg-[oklch(0.7_0.19_25)] text-[13px] text-ink">
            Confirm purge
          </button>
          <button type="button" onClick={() => setArmed(false)} className="h-8 rounded-md border border-line px-3 text-[13px]">
            Cancel
          </button>
        </div>
      )}
      {note && <p className="text-sm text-muted">{note}</p>}
    </section>
  )
}
