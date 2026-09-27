import { useRef } from 'react'

export function AddContext() {
  const dialog = useRef<HTMLDialogElement>(null)

  return <>
    <button
      type="button"
      onClick={() => dialog.current?.showModal()}
      className="rounded-md border border-accent px-4 py-2 text-sm font-medium text-accent"
    >
      + Add context
    </button>
    <dialog
      ref={dialog}
      aria-labelledby="add-context-title"
      aria-describedby="add-context-description"
      onKeyDown={(event) => event.stopPropagation()}
      className="m-auto max-h-[90vh] w-[min(560px,calc(100vw-32px))] overflow-y-auto rounded-[10px] border border-line bg-panel p-5 text-ink backdrop:bg-black/60"
    >
      <form onSubmit={(event) => event.preventDefault()} className="flex flex-col gap-4">
        <div className="flex items-start justify-between gap-4">
          <h2 id="add-context-title" className="text-[30px] font-semibold leading-tight tracking-tight">Add more context</h2>
          <button type="button" aria-label="Close context form" onClick={() => dialog.current?.close()} className="rounded px-2 py-1 text-muted">✕</button>
        </div>
        <p id="add-context-description" className="text-sm text-muted">
          Add details about people, preferences, or experiences. This form is a preview; nothing is saved or sent.
        </p>
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Name or topic</span>
          <input
            name="topic"
            placeholder="For example, family or a recent vacation"
            className="h-10 rounded-md border border-[oklch(0.33_0.012_160)] bg-[oklch(0.165_0.008_160)] px-3 outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Additional context</span>
          <textarea
            name="context"
            rows={8}
            placeholder="Describe what you would like Flick to know, including who each detail is about."
            className="rounded-md border border-[oklch(0.33_0.012_160)] bg-[oklch(0.165_0.008_160)] px-3 py-2 leading-relaxed outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => dialog.current?.close()} className="rounded-md border border-line px-4 py-2 text-sm">Close</button>
          <button type="button" disabled className="rounded-md bg-accent px-4 py-2 font-semibold text-[oklch(0.17_0.03_158)] opacity-50">Save context (coming soon)</button>
        </div>
      </form>
    </dialog>
  </>
}
