export interface TranscriptLine {
  who: string
  text: string
}

export function Transcript({ lines }: { lines: TranscriptLine[] }) {
  return (
    <div className="flex min-h-[140px] flex-1 flex-col gap-2 rounded-[10px] border border-line bg-panel px-4 py-3">
      <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Transcript</span>
      <div className="flex flex-col gap-2 overflow-auto">
        {lines.length === 0 && <span className="text-sm text-muted">Nobody has spoken yet.</span>}
        {lines.map((line, i) => (
          <p key={`${i}-${line.text.slice(0, 12)}`} className="text-sm leading-snug">
            <span className="font-mono text-[10.5px] uppercase tracking-wide text-accent">{line.who}</span>
            <span className="mt-0.5 block text-ink">{line.text}</span>
          </p>
        ))}
      </div>
    </div>
  )
}
