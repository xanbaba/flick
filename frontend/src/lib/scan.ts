// Step-scan view state (four tiles, Cancel last). The backend owns the scan:
// it sends scan.targets / scan.highlight / scan.selected / scan.idle, and the
// page only mirrors them. In the legacy five-tile keyboard mode no scan.*
// messages arrive, so `ScanView` stays null and number keys work as before.

import type { WsMessage } from './types'

export interface ScanView {
  trialId: string
  labels: string[]
  cancelIdx: number
  highlightIdx: number
  selectedIdx: number | null
}

export function reduceScan(scan: ScanView | null, msg: WsMessage): ScanView | null {
  switch (msg.type) {
    case 'scan.targets':
      return {
        trialId: msg.payload.trial_id,
        labels: msg.payload.labels,
        cancelIdx: msg.payload.cancel_idx,
        highlightIdx: msg.payload.highlight_idx,
        selectedIdx: null,
      }
    case 'scan.highlight':
      if (!scan || scan.trialId !== msg.payload.trial_id || scan.selectedIdx !== null) return scan
      return { ...scan, highlightIdx: msg.payload.highlight_idx }
    case 'scan.selected':
      if (!scan || scan.trialId !== msg.payload.trial_id) return scan
      return { ...scan, highlightIdx: msg.payload.target_idx, selectedIdx: msg.payload.target_idx }
    case 'scan.idle':
      if (scan && msg.payload.trial_id !== null && scan.trialId !== msg.payload.trial_id) return scan
      return null
    default:
      return scan
  }
}

/** Map a keyboard key to a key_press key. n / → move, s / Enter / Space select, digits pick. */
export function scanKey(key: string, scan: ScanView | null, legacyTargets = 5): string | null {
  if (scan) {
    if (key === 'n' || key === 'N' || key === 'ArrowRight' || key === 'ArrowDown') return 'n'
    if (key === 's' || key === 'S' || key === 'Enter' || key === ' ') return 's'
    const n = Number(key)
    if (Number.isInteger(n) && n >= 1 && n <= scan.labels.length) return key
    return null
  }
  const n = Number(key)
  return Number.isInteger(n) && n >= 1 && n <= legacyTargets ? key : null
}
