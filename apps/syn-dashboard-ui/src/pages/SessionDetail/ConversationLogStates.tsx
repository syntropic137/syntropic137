export function ModalOverlay({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      {children}
    </div>
  )
}

export function LogLoadingState() {
  return (
    <ModalOverlay>
      <div className="rounded-xl bg-[var(--color-surface)] p-8">
        <div className="animate-pulse text-[var(--color-text-secondary)]">
          Loading transcript...
        </div>
      </div>
    </ModalOverlay>
  )
}

export function LogErrorState({ error, onClose }: { error: string | null; onClose: () => void }) {
  return (
    <ModalOverlay>
      <div className="max-w-lg rounded-xl bg-[var(--color-surface)] p-8">
        <div className={error ? 'text-red-400' : 'text-[var(--color-text-muted)]'}>
          {error ? `Error: ${error}` : 'No transcript available for this session.'}
        </div>
        <button
          onClick={onClose}
          className="mt-4 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm"
        >
          Close
        </button>
      </div>
    </ModalOverlay>
  )
}
