import { useCallback, useEffect, useRef, useState } from 'react'

import { StatusBar } from './components/StatusBar'
import { api } from './lib/api'
import { playAudio, speak, unlockAudio } from './lib/playback'
import type { MemoryBrain } from './lib/brain'
import { emptyStreams, type Streams } from './lib/streams'
import type { AnalyticsSummary, FsmState, SysStatusPayload, WsMessage, WsPayloads } from './lib/types'
import { FlickSocket, type ConnState, wsUrl } from './lib/ws'
import { Dashboard } from './views/Dashboard'
import { Onboarding } from './views/Onboarding'
import type { TranscriptLine } from './components/Transcript'

interface Dash {
  conn: ConnState
  seeded: boolean | null
  bootError: string | null
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
  graphNodes: number
}

const initial: Dash = {
  conn: { state: 'connecting', retryMs: 0 },
  seeded: null,
  bootError: null,
  status: null,
  fsm: 'UNSEEDED',
  detail: '',
  transcript: [],
  labels: [],
  round: null,
  selectedIdx: null,
  spoken: null,
  grounding: [],
  analytics: null,
  flows: [],
  cost: null,
  spectator: { url: null, connected_viewers: 0 },
  graphNodes: 0,
}

export function App() {
  const [dash, setDash] = useState<Dash>(initial)
  const socketRef = useRef<FlickSocket | null>(null)
  const brainRef = useRef<MemoryBrain | null>(null)
  const streams = useRef<Streams>(emptyStreams())
  const pending = useRef<{ snapshot: WsPayloads['graph.snapshot'] | null; blooms: WsPayloads['graph.bloom'][] }>({
    snapshot: null,
    blooms: [],
  })

  const onBrain = useCallback((brain: MemoryBrain | null) => {
    brainRef.current = brain
    if (!brain) return
    if (pending.current.snapshot) brain.setSnapshot(pending.current.snapshot)
    for (const batch of pending.current.blooms) brain.bloom(batch)
    pending.current.blooms = []
  }, [])

  useEffect(() => {
    let alive = true
    void api
      .onboardingStatus()
      .then((status) => {
        if (alive) setDash((d) => ({ ...d, seeded: status.seeded, bootError: null, graphNodes: status.node_count }))
      })
      .catch((err: unknown) => {
        if (alive) setDash((d) => ({ ...d, bootError: err instanceof Error ? err.message : 'Backend unreachable' }))
      })

    const socket = new FlickSocket(
      wsUrl(),
      (msg) => {
        if (msg.type === 'graph.snapshot') {
          pending.current.snapshot = msg.payload
          brainRef.current?.setSnapshot(msg.payload)
        } else if (msg.type === 'graph.bloom') {
          if (brainRef.current) brainRef.current.bloom(msg.payload)
          else pending.current.blooms.push(msg.payload)
        } else if (msg.type === 'graph.activate') {
          brainRef.current?.activate(msg.payload)
          if (msg.payload.reason === 'grounding') brainRef.current?.glow(msg.payload.node_ids)
        } else if (msg.type === 'conv.spoken') {
          if (msg.payload.voice === 'browser') speak(msg.payload.text)
          else if (msg.payload.audio_b64) playAudio(msg.payload.audio_b64, msg.payload.voice)
        }
        setDash((d) => reduce(d, msg))
      },
      (msg) => {
        if (msg.type === 'eeg.trace') streams.current.eeg = msg.payload
        else if (msg.type === 'eeg.psd') streams.current.psd = msg.payload
        else if (msg.type === 'bci.scores') streams.current.scores = msg.payload
      },
      (conn) => setDash((d) => ({ ...d, conn })),
    )
    socketRef.current = socket
    socket.start()

    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof HTMLElement && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return
      if (event.key >= '1' && event.key <= '5') {
        unlockAudio()
        socket.send({ type: 'client.key_press', ts: Date.now() / 1000, key: event.key })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      alive = false
      window.removeEventListener('keydown', onKey)
      socket.close()
      socketRef.current = null
    }
  }, [])

  return (
    <div className="flex min-h-full flex-col">
      <StatusBar conn={dash.conn} status={dash.status} />
      {dash.seeded === null && (
        <p className="p-6 text-sm text-muted">{dash.bootError ?? 'Waiting for the backend…'}</p>
      )}
      {dash.seeded === false && (
        <Onboarding
          brainRef={brainRef}
          empty={dash.graphNodes === 0}
          onReady={onBrain}
          onSeeded={() => setDash((d) => ({ ...d, seeded: true, fsm: 'IDLE' }))}
        />
      )}
      {dash.seeded === true && (
        <Dashboard
          socket={socketRef.current}
          brainRef={brainRef}
          streams={streams}
          empty={dash.graphNodes === 0}
          onReady={onBrain}
          status={dash.status}
          fsm={dash.fsm}
          detail={dash.detail}
          transcript={dash.transcript}
          labels={dash.labels}
          round={dash.round}
          selectedIdx={dash.selectedIdx}
          spoken={dash.spoken}
          grounding={dash.grounding}
          analytics={dash.analytics}
          flows={dash.flows}
          cost={dash.cost}
          spectator={dash.spectator}
        />
      )}
    </div>
  )
}

function reduce(d: Dash, msg: WsMessage): Dash {
  switch (msg.type) {
    case 'sys.status':
      return { ...d, status: msg.payload }
    case 'fsm.state':
      return {
        ...d,
        fsm: msg.payload.state,
        detail: msg.payload.detail,
        seeded: msg.payload.state === 'UNSEEDED' ? false : d.seeded,
      }
    case 'conv.transcript':
      return {
        ...d,
        transcript: [{ who: msg.payload.partner_name || msg.payload.speaker, text: msg.payload.text }, ...d.transcript].slice(0, 8),
      }
    case 'conv.intents':
      return { ...d, labels: msg.payload.labels, round: 'intent', selectedIdx: null, spoken: null }
    case 'conv.candidates':
      return {
        ...d,
        labels: msg.payload.candidates,
        round: 'candidate',
        grounding: msg.payload.grounding,
        selectedIdx: null,
      }
    case 'input.selection':
      return { ...d, selectedIdx: msg.payload.target_idx, round: msg.payload.round }
    case 'conv.spoken':
      return { ...d, spoken: msg.payload }
    case 'analytics.summary':
      return { ...d, analytics: msg.payload }
    case 'privacy.flow':
      return { ...d, flows: [...d.flows, msg.payload].slice(-40) }
    case 'privacy.cost':
      return { ...d, cost: msg.payload }
    case 'spectator.link':
      return { ...d, spectator: { url: msg.payload.url || null, connected_viewers: msg.payload.connected_viewers } }
    case 'graph.snapshot':
      return { ...d, graphNodes: msg.payload.nodes.length }
    case 'graph.bloom':
      return { ...d, graphNodes: d.graphNodes + msg.payload.nodes.length }
    default:
      return d
  }
}
