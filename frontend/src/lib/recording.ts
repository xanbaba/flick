export interface Recording {
  stop(): void
  cancel(): void
}

export async function startRecording(
  signal: AbortSignal,
  complete: (audio: Blob) => void,
  failed: (error: Error) => void,
): Promise<Recording> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    throw new Error('Microphone recording requires localhost or HTTPS and a supported browser.')
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const release = () => stream.getTracks().forEach((track) => track.stop())
  if (signal.aborted) {
    release()
    throw new DOMException('Recording cancelled', 'AbortError')
  }
  const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
    .find((type) => MediaRecorder.isTypeSupported(type))
  let recorder: MediaRecorder
  try {
    if (!mimeType) throw new Error('This browser does not support an uploadable audio format.')
    recorder = new MediaRecorder(stream, { mimeType })
  } catch (error) {
    release()
    throw error
  }
  const chunks: Blob[] = []
  let cancelled = false
  const stop = () => { if (recorder.state !== 'inactive') recorder.stop() }
  const cancel = () => { cancelled = true; stop(); release() }
  signal.addEventListener('abort', cancel, { once: true })
  recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
  recorder.onerror = () => { cancel(); failed(new Error('Microphone recording failed. Please try again.')) }
  recorder.onstop = () => {
    release()
    signal.removeEventListener('abort', cancel)
    if (!cancelled) complete(new Blob(chunks, { type: recorder.mimeType }))
  }
  try { recorder.start() } catch (error) {
    signal.removeEventListener('abort', cancel)
    release()
    throw error
  }
  return { stop, cancel }
}
