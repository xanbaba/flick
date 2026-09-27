import { useEffect, useState } from 'react'

import { CandidatePanel } from '../components/CandidatePanel'
import { EegTraceView } from '../components/EegTrace'
import { MemoryBrainView } from '../components/MemoryBrain'
import { PrivacyPanel } from '../components/PrivacyPanel'
import { PsdPlotView } from '../components/PsdPlot'
import { SessionAnalytics } from '../components/SessionAnalytics'
import { SpectatorQR } from '../components/SpectatorQR'
import { TargetScores } from '../components/TargetScores'
import { Transcript, type TranscriptLine } from '../components/Transcript'
import { api } from '../lib/api'
import type { MemoryBrain } from '../lib/brain'
import type { Streams } from '../lib/streams'
import type { AnalyticsSummary, FsmState, SysStatusPayload, WsPayloads } from '../lib/types'
import type { FlickSocket } from '../lib/ws'

type Tab = 'analytics' | 'privacy' | 'spectator'

export function Dashboard({
  socket,
  brainRef,
  streams,
  empty,
  onReady,
  status,
  fsm,
  detail,
  transcript,
  labels,
  round,
  selectedIdx,
  spoken,
  grounding,
  analytics,
  flows,
  cost,
  spectator,
}: {
  socket: FlickSocket | null
  brainRef: React.MutableRefObject<MemoryBrain | null>
  streams: React.MutableRefObject<Streams>
  empty: boolean
  onReady: (brain: MemoryBrain | null) => void
  status: SysStatusPayload | null
  fsm: FsmState
  detail: string
  transcript: TranscriptLine[]
  labels: string[]
  round: 'intent' | 'candidate' | 'speller' | null
  selectedIdx: number | null
  spoken: WsPayloads['conv.spoken'] | null
  grounding: string[]
  analytics: AnalyticsSummary | null
  flows: WsPayloads['privacy.flow'][]
  cost: WsPayloads['privacy.cost'] | null
  spectator: WsPayloads['spectator.link']
}) {
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 900px)').matches)
  const [tab, setTab] = useState<Tab>('analytics')

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    const onChange = () => setNarrow(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const frequencies = status?.frequencies ?? []
  const cancelIdx = status?.cancel_idx ?? -1
  const show = (name: Tab) => !narrow || tab === name

  return (
    <main className="flex flex-1 flex-col gap-2.5 p-2.5">
      <section className="grid gap-2.5 lg:min-h-[460px] lg:grid-cols-[minmax(0,1.5fr)_minmax(320px,1fr)]">
        <MemoryBrainView brainRef={brainRef} empty={empty} onReady={onReady} />
        <div className="flex min-h-0 flex-col gap-2.5">
          <Transcript lines={transcript} />
          <TargetScores streams={streams} labels={labels} frequencies={frequencies} cancelIdx={cancelIdx} />
          <PsdPlotView streams={streams} frequencies={frequencies} cancelIdx={cancelIdx} />
        </div>
      </section>
      <EegTraceView streams={streams} />
      <CandidatePanel
        socket={socket}
        fsm={fsm}
        detail={detail}
        labels={labels}
        round={round}
        selectedIdx={selectedIdx}
        spoken={spoken}
        grounding={grounding}
      />
      {narrow && (
        <div className="flex gap-1 rounded-lg border border-line bg-[oklch(0.165_0.008_160)] p-1 font-mono text-[11px]">
          {(['analytics', 'privacy', 'spectator'] as const).map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setTab(name)}
              className={`h-8 flex-1 rounded-md capitalize ${tab === name ? 'bg-[oklch(0.26_0.012_160)]' : ''}`}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      <div className={narrow ? 'flex flex-col gap-2.5' : 'grid grid-cols-3 gap-2.5'}>
        {show('analytics') && <SessionAnalytics summary={analytics} />}
        {show('privacy') && (
          <PrivacyPanel
            localMode={Boolean(status?.local_mode)}
            flows={flows}
            cost={cost}
            onLocalMode={(enabled) => {
              void api.localMode(enabled)
            }}
          />
        )}
        {show('spectator') && <SpectatorQR url={spectator.url} viewers={spectator.connected_viewers} />}
      </div>
    </main>
  )
}
