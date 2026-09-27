import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { unlockAudio } from '../lib/playback'
import { startRecording, type Recording } from '../lib/recording'

export function SpeechRecorder({ ready, onBusy }: { ready: boolean; onBusy: (busy: boolean) => void }) {
  const [phase, setPhase] = useState<'idle' | 'starting' | 'recording' | 'sending'>('idle')
  const [error, setError] = useState('')
  const recording = useRef<Recording | null>(null)
  const abort = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearTimer = () => { if (timer.current) clearTimeout(timer.current); timer.current = null }

  useEffect(() => () => { abort.current?.abort(); clearTimer() }, [])
  useEffect(() => {
    if (!ready && (phase === 'starting' || recording.current)) {
      abort.current?.abort()
      recording.current = null
      clearTimer()
      setPhase('idle')
      onBusy(false)
    }
  }, [ready, onBusy, phase])

  async function start() {
    unlockAudio()
    const controller = new AbortController()
    abort.current = controller
    setError('')
    setPhase('starting')
    onBusy(true)
    try {
      recording.current = await startRecording(controller.signal, (audio) => {
        recording.current = null
        clearTimer()
        setPhase('sending')
        void (async () => {
          try {
            const transcript = await api.transcribeRecording(audio, controller.signal)
            if (!controller.signal.aborted) await api.utterance(transcript.text)
          } catch (err) {
            if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Transcription failed.')
          } finally {
            if (!controller.signal.aborted) { setPhase('idle'); onBusy(false) }
          }
        })()
      }, (err) => {
        clearTimer()
        recording.current = null
        setError(err.message)
        setPhase('idle')
        onBusy(false)
      })
      setPhase('recording')
      timer.current = setTimeout(() => recording.current?.stop(), 60_000)
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : 'Microphone access failed.')
        setPhase('idle')
        onBusy(false)
      }
    }
  }

  return <div className="flex flex-wrap items-center gap-3">
    <button type="button"
      disabled={phase === 'starting' || phase === 'sending' || (!ready && phase !== 'recording')}
      onClick={() => phase === 'recording' ? recording.current?.stop() : void start()}
      className="rounded-lg border border-accent px-4 py-2 text-sm font-medium disabled:opacity-40">
      {phase === 'recording' ? 'Stop & send' : phase === 'starting' ? 'Opening microphone…' : phase === 'sending' ? 'Processing recording…' : 'Record partner'}
    </button>
    <span role="status" className="text-sm text-muted">
      {phase === 'recording' ? 'Recording — press Stop & send when finished (60 seconds maximum).' : 'Microphone records only when you press Record.'}
    </span>
    {error && <span role="alert" className="text-sm text-red-400">{error}</span>}
  </div>
}
