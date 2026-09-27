import { useState } from 'react'

import { api } from '../lib/api'
import { unlockAudio } from '../lib/playback'
import type { ScanView } from '../lib/scan'
import type { FlickSocket } from '../lib/ws'
import type { FsmState, SysStatusPayload, WsPayloads } from '../lib/types'

const STEPS: FsmState[] = [
  'TRANSCRIBING',
  'GROUNDING',
  'INTENT_GEN',
  'INTENT_WAIT',
  'CANDIDATE_GEN',
  'CANDIDATE_WAIT',
  'SPEAKING',
  'LEARNING',
]

const WAITING = new Set<FsmState>(['INTENT_WAIT', 'CANDIDATE_WAIT'])
const GENERATING = new Set<FsmState>(['TRANSCRIBING', 'GROUNDING', 'INTENT_GEN', 'CANDIDATE_GEN'])

export function CandidatePanel({
  socket,
  fsm,
  detail,
  labels,
  round,
  selectedIdx,
  scan = null,
  status = null,
  spoken,
  fallback,
  grounding,
}: {
  socket: FlickSocket | null
  fsm: FsmState
  detail: string
  labels: string[]
  round: 'intent' | 'candidate' | 'speller' | null
  selectedIdx: number | null
  scan?: ScanView | null
  status?: SysStatusPayload | null
  spoken: WsPayloads['conv.spoken'] | null
  fallback: boolean
  grounding: string[]
}) {
  const [prompt, setPrompt] = useState('')
  const [sendError, setSendError] = useState<string | null>(null)

  function press(key: string) {
    unlockAudio()
    socket?.send({ type: 'client.key_press', ts: Date.now() / 1000, key, trial_id: scan?.trialId ?? null })
  }

  async function sendPrompt() {
    const text = prompt.trim()
    if (!text) return
    unlockAudio()
    setSendError(null)
    setPrompt('')
    try {
      await api.utterance(text)
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Utterance failed')
    }
  }

  const speaking = (fsm === 'SPEAKING' || fsm === 'LEARNING') && spoken != null
  const showTiles = WAITING.has(fsm)
  const bci = status?.input_source === 'bci'
  const sensorBlocked = bci && status?.ready === false
  const scanHint = bci
    ? 'Clench your jaw to move · close your eyes ~2 s to choose'
    : 'n or → to move · s or Enter to choose · number keys pick directly'

  return (
    <section className="flex flex-col gap-3 rounded-[10px] border border-line bg-panel px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Conversation</span>
        <div className="flex min-w-0 flex-1 flex-wrap gap-1">
          {STEPS.map((step) => {
            const on = step === fsm
            return (
              <span
                key={step}
                className={`rounded-md border px-2 py-1 font-mono text-[9.5px] uppercase tracking-wide ${
                  on ? 'border-accent/70 bg-accent/10 text-accent' : 'border-line text-muted'
                }`}
              >
                {step.replace('_', ' ')}
              </span>
            )
          })}
        </div>
      </div>

      {showTiles && fallback && (
        <p role="status" className="text-sm text-muted">
          {round === 'candidate'
            ? 'Fallback reply: your selected intent, unchanged.'
            : 'Fallback choices: generation is unavailable.'}
        </p>
      )}
      {(sensorBlocked || (showTiles && scan)) && (
        <p role="status" aria-live="polite" className="flex flex-wrap items-center gap-2 text-sm">
          {sensorBlocked && (
            <span className="rounded-md bg-[oklch(0.7_0.19_25/0.16)] px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-[oklch(0.78_0.16_30)]">
              Headset: {status?.blocked_reason ?? 'not ready'}
            </span>
          )}
          {showTiles && scan && <span className="text-muted">{scanHint}</span>}
        </p>
      )}
      <div className="flex min-h-[118px] items-stretch gap-2.5">
        {!showTiles && !GENERATING.has(fsm) && !speaking && (
          <div className="flex flex-1 flex-col justify-center gap-2 rounded-lg border border-dashed border-[oklch(0.33_0.012_160)] px-4 py-3.5">
            <span className="text-xl font-medium text-[oklch(0.76_0.012_160)]">Listening</span>
            <span className="text-sm text-muted">
              {detail || (scan || bci ? `Type what the partner says, then: ${scanHint}.` : 'Type what the partner says, then choose with keys 1–5.')}
            </span>
          </div>
        )}
        {GENERATING.has(fsm) && (
          <div className="flex flex-1 flex-col justify-center gap-3 rounded-lg border border-line bg-[oklch(0.165_0.008_160)] px-4 py-3.5">
            <span className="text-xl font-medium">{fsm.replace('_', ' ')}</span>
            <span className="font-mono text-[11px] text-muted">{detail}</span>
          </div>
        )}
        {showTiles &&
          labels.map((label, i) => {
            const chosen = selectedIdx === i || scan?.selectedIdx === i
            const lit = scan != null && scan.selectedIdx === null && scan.highlightIdx === i
            return (
              <button
                key={`${round}-${i}-${label}`}
                type="button"
                disabled={!label.trim()}
                aria-current={lit ? 'true' : undefined}
                onClick={() => press(String(i + 1))}
                className={`flex min-w-0 flex-col gap-2 rounded-lg border px-3.5 py-3 text-left transition-all duration-150 ${
                  chosen
                    ? 'flex-[2] border-accent bg-accent/10'
                    : lit
                      ? 'flex-[1.4] border-2 border-accent bg-accent/15 shadow-[0_0_0_3px_oklch(0.8_0.15_160/0.25)]'
                      : 'flex-1 border-line bg-[oklch(0.165_0.008_160)]'
                }`}
              >
                <span className="flex items-center justify-between font-mono text-[10.5px] uppercase tracking-wide text-muted">
                  <span>{lit ? `▶ ${i + 1}` : i + 1}</span>
                  <span>{i === labels.length - 1 && label === 'Cancel' ? 'cancel' : round ?? ''}</span>
                </span>
                <span className={`leading-snug ${chosen || lit ? 'text-lg font-medium text-ink' : 'text-sm text-[oklch(0.86_0.01_160)]'}`}>
                  {label || 'Unused'}
                </span>
              </button>
            )
          })}
        {speaking && spoken && (
          <div className="flex flex-1 flex-col gap-3 rounded-lg border border-accent/70 bg-accent/10 px-5 py-4">
            <div className="flex flex-wrap items-center gap-3 font-mono text-[10.5px]">
              <span className="font-semibold tracking-widest text-accent">SPEAKING</span>
              <span className="text-ink">{spoken.voice}</span>
              <span className="text-muted">{spoken.cached ? 'cached' : `${spoken.latency_ms.toFixed(0)} ms`}</span>
            </div>
            <p className="text-3xl font-medium leading-snug tracking-tight">{spoken.text}</p>
          </div>
        )}
      </div>

      {grounding.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[10.5px] tracking-wide text-muted">GROUNDED IN</span>
          {grounding.map((id) => (
            <span key={id} className="rounded-full border border-line bg-[oklch(0.2_0.009_160)] px-2.5 py-0.5 text-[12.5px]">
              {id}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2.5">
        <span className="font-mono text-[10.5px] text-muted" title="Sends the partner line over HTTP. Selection still arrives as client.key_press.">
          SCRIPTED PROMPT
        </span>
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void sendPrompt()
          }}
          placeholder="Type what the partner says"
          className="h-8 w-[280px] max-w-[42vw] rounded-md border border-[oklch(0.33_0.012_160)] bg-[oklch(0.165_0.008_160)] px-2.5 text-[13px] outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        />
        <button
          type="button"
          onClick={() => void sendPrompt()}
          className="h-8 rounded-md border border-[oklch(0.33_0.012_160)] bg-[oklch(0.22_0.01_160)] px-3 text-[13px]"
        >
          Send
        </button>
        {sendError && <span className="text-sm text-[oklch(0.78_0.16_30)]">{sendError}</span>}
      </div>
    </section>
  )
}
