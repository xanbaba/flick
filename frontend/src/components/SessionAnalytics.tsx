import type { AnalyticsSummary } from '../lib/types'

export function SessionAnalytics({ summary }: { summary: AnalyticsSummary | null }) {
  const cued = summary?.cued_trials ?? 0
  const accuracy = summary?.accuracy_pct
  const itr = summary?.itr_bits_per_min

  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-[10px] border border-line bg-panel px-4 py-3.5">
      <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Session analytics</span>
      {cued === 0 ? (
        <p className="text-sm text-muted">No cued trials yet. Accuracy and information transfer rate stay blank until a cued block is recorded.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 font-mono text-[12px]">
          <Metric label="accuracy" value={accuracy == null ? '—' : `${accuracy.toFixed(1)}%`} />
          <Metric label="ITR" value={itr == null ? '—' : `${itr.toFixed(2)} bit/min`} />
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 font-mono text-[12px] text-[oklch(0.76_0.012_160)]">
        <Metric label="selections" value={String(summary?.selections_total ?? 0)} />
        <Metric label="mean latency" value={`${(summary?.mean_selection_latency_s ?? 0).toFixed(2)} s`} />
        <Metric label="cued trials" value={String(cued)} />
        <Metric label="drift" value={(summary?.drift ?? 0).toFixed(3)} />
      </div>
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-widest text-muted">{label}</span>
      <span className="tabular-nums text-ink">{value}</span>
    </div>
  )
}
