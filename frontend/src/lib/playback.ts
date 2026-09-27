import type { WsPayloads } from './types'

const player = new Audio()
let unlocked = false
let unlocking = false

const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='

export function unlockAudio(): void {
  if (unlocked || unlocking || !player.paused) return
  unlocking = true
  player.muted = true
  player.src = SILENT_WAV
  void player
    .play()
    .then(() => {
      unlocked = true
      if (player.src === SILENT_WAV) {
        player.pause()
        player.muted = false
      }
    })
    .catch(() => {
      player.muted = false
    })
    .finally(() => { unlocking = false })
}

let cancelActive: (() => void) | null = null

export function stopPlayback(): void {
  cancelActive?.()
}

export function playAudio(audioB64: string, voice: string): Promise<void> {
  stopPlayback()
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      player.onended = null
      player.onerror = null
      cancelActive = null
      player.pause()
      if (error) reject(error)
      else resolve()
    }
    cancelActive = () => finish(new Error('Playback stopped'))
    player.onended = () => finish()
    player.onerror = () => finish(new Error('Audio playback failed'))
    player.muted = false
    // Cached Piper audio still contains WAV bytes even though voice is "cache".
    try {
      const header = atob(audioB64.slice(0, 16))
      const wav = header.startsWith('RIFF') && header.slice(8, 12) === 'WAVE'
      const mime = wav || voice === 'piper' ? 'audio/wav' : 'audio/mpeg'
      player.src = `data:${mime};base64,${audioB64}`
      void player.play().catch(() => finish(new Error('Audio playback blocked')))
    } catch {
      finish(new Error('Invalid audio payload'))
    }
  })
}

export function speak(text: string): Promise<void> {
  stopPlayback()
  return new Promise((resolve, reject) => {
    if (!('speechSynthesis' in window)) {
      reject(new Error('Browser speech is unavailable'))
      return
    }
    const utterance = new SpeechSynthesisUtterance(text)
    let settled = false
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      utterance.onend = null
      utterance.onerror = null
      cancelActive = null
      if (error) reject(error)
      else resolve()
    }
    cancelActive = () => {
      finish(new Error('Playback stopped'))
      window.speechSynthesis.cancel()
    }
    utterance.onend = () => finish()
    utterance.onerror = () => finish(new Error('Browser speech failed'))
    try {
      window.speechSynthesis.speak(utterance)
    } catch {
      finish(new Error('Browser speech failed'))
    }
  })
}

export async function playReply(payload: WsPayloads['conv.spoken']): Promise<'completed' | 'failed'> {
  const deadline = payload.playback_timeout_s
  const timer = deadline != null ? setTimeout(stopPlayback, deadline * 1000) : undefined
  try {
    if (payload.voice === 'browser') await speak(payload.text)
    else if (payload.audio_b64) await playAudio(payload.audio_b64, payload.voice)
    else throw new Error('Reply has no audio')
    return 'completed'
  } catch (error) {
    console.warn('flick: playback failed', error)
    return 'failed'
  } finally {
    clearTimeout(timer)
  }
}
