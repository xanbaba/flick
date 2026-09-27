export interface OnboardingStatus {
  seeded: boolean
  node_count: number
}

export interface SeedResult {
  seeded: boolean
  node_count: number
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof body?.detail === 'string' ? body.detail : `${method} ${path}: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  transcribeRecording: async (audio: Blob, signal: AbortSignal): Promise<{ text: string; confidence: number }> => {
    const res = await fetch('/api/speech/transcribe', {
      method: 'POST', headers: { 'Content-Type': audio.type }, body: audio, signal,
    })
    const body = await res.json().catch(() => null)
    if (!res.ok) throw new Error(body?.detail ?? 'Recording upload failed.')
    return body
  },
  onboardingStatus: () => request<OnboardingStatus>('GET', '/api/onboarding/status'),
  seed: (bio: string, name: string) => request<SeedResult>('POST', '/api/onboarding/seed', { bio, name }),
  utterance: (text: string) => request<{ state: string; trial_id: string | null }>('POST', '/api/utterance', { text }),
  purge: (scope: string) => request<{ scope: string }>('POST', '/api/privacy/purge', { scope }),
  spectatorLink: () => request<{ url: string; connected_viewers: number }>('GET', '/api/spectator/link'),
}
