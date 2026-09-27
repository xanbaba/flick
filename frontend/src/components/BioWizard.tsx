import { useState } from 'react'

import { api } from '../lib/api'
import { PERSONA_BIO, PERSONA_NAME } from '../lib/persona'

export function BioWizard({ onSeeded }: { onSeeded: () => void }) {
  const [name, setName] = useState(PERSONA_NAME)
  const [bio, setBio] = useState(PERSONA_BIO)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.seed(bio, name.trim() || PERSONA_NAME)
      onSeeded()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Seed failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-[10px] border border-line bg-panel p-5">
      <h1 className="text-[34px] font-semibold leading-tight tracking-tight">Who will be speaking through Flick?</h1>
      <p className="text-sm text-muted">One biography. The graph grows from this text. You can edit it before seeding.</p>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-10 rounded-md border border-[oklch(0.33_0.012_160)] bg-[oklch(0.165_0.008_160)] px-3 outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Biography</span>
        <textarea
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          rows={10}
          className="rounded-md border border-[oklch(0.33_0.012_160)] bg-[oklch(0.165_0.008_160)] px-3 py-2 leading-relaxed outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <button
        type="button"
        disabled={busy || !bio.trim()}
        onClick={() => void submit()}
        className="h-11 rounded-md bg-accent font-semibold text-[oklch(0.17_0.03_158)] disabled:opacity-50"
      >
        {busy ? 'Seeding…' : 'Seed the memory graph'}
      </button>
      {error && <p className="text-sm text-[oklch(0.78_0.16_30)]">{error}</p>}
    </div>
  )
}
