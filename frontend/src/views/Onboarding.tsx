import type { MemoryBrain } from '../lib/brain'
import { BioWizard } from '../components/BioWizard'
import { MemoryBrainView } from '../components/MemoryBrain'

export function Onboarding({
  brainRef,
  empty,
  onReady,
  onSeeded,
}: {
  brainRef: React.MutableRefObject<MemoryBrain | null>
  empty: boolean
  onReady: (brain: MemoryBrain | null) => void
  onSeeded: () => void
}) {
  return (
    <main className="grid flex-1 gap-2.5 p-2.5 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,1fr)]">
      <MemoryBrainView brainRef={brainRef} empty={empty} onReady={onReady} />
      <BioWizard onSeeded={onSeeded} />
    </main>
  )
}
