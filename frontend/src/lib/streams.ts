import type { WsPayloads } from './types'

export interface Streams {
  eeg: WsPayloads['eeg.trace'] | null
  psd: WsPayloads['eeg.psd'] | null
  scores: WsPayloads['bci.scores'] | null
  eegDrawn: WsPayloads['eeg.trace'] | null
  psdDrawn: WsPayloads['eeg.psd'] | null
}

export function emptyStreams(): Streams {
  return { eeg: null, psd: null, scores: null, eegDrawn: null, psdDrawn: null }
}
