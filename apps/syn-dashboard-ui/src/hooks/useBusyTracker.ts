import { useState } from 'react'

export function useBusyTracker() {
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())

  const addBusy = (id: string) => setBusyIds((prev) => new Set(prev).add(id))

  const removeBusy = (id: string) =>
    setBusyIds((prev) => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })

  return { busyIds, addBusy, removeBusy }
}
