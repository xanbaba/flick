import { useEffect, useRef, useState } from 'react'

import { MemoryBrain } from '../lib/brain'

export function MemoryBrainView({
  brainRef,
  empty,
  onReady,
}: {
  brainRef: React.MutableRefObject<MemoryBrain | null>
  empty: boolean
  onReady: (brain: MemoryBrain | null) => void
}) {
  const el = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const node = el.current
    if (!node) return
    node.replaceChildren()
    const brain = new MemoryBrain(node)
    brainRef.current = brain
    onReady(brain)
    setReady(true)
    return () => {
      brain.destroy()
      node.replaceChildren()
      if (brainRef.current === brain) brainRef.current = null
      onReady(null)
      setReady(false)
    }
  }, [brainRef, onReady])

  const hint = !ready ? 'Loading 3D renderer…' : empty ? 'No memories yet' : ''

  return (
    <div className="relative min-h-[320px] overflow-hidden rounded-[10px] border border-line bg-[oklch(0.14_0.008_160)] lg:h-full">
      <div ref={el} className="absolute inset-0" />
      {hint && (
        <div className="pointer-events-none absolute bottom-3 left-3 font-mono text-[11px] tracking-wide text-muted">
          {hint}
        </div>
      )}
    </div>
  )
}
