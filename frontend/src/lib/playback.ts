const player = new Audio()

const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='

export function unlockAudio(): void {
  player.muted = true
  if (!player.src) player.src = SILENT_WAV
  void player
    .play()
    .then(() => {
      player.pause()
      player.muted = false
    })
    .catch(() => {
      player.muted = false
    })
}

export function playAudio(audioB64: string, voice: string): void {
  player.muted = false
  const mime = voice === 'piper' ? 'audio/wav' : 'audio/mpeg'
  player.src = `data:${mime};base64,${audioB64}`
  void player.play().catch((err: unknown) => {
    console.warn('flick: audio playback blocked', err)
  })
}

export function speak(text: string): void {
  if (!('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}
