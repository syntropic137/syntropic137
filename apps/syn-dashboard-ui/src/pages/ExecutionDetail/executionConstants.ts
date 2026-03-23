import { CheckCircle2, Clock, OctagonX, Play, XCircle } from 'lucide-react'

export const phaseStatusIcons: Record<string, typeof Play> = {
  pending: Clock,
  running: Play,
  completed: CheckCircle2,
  failed: XCircle,
  interrupted: OctagonX,
  cancelled: OctagonX,
}

export const phaseStatusColors: Record<string, string> = {
  pending: 'border-slate-500/30 bg-slate-500/10',
  running: 'border-blue-500/30 bg-blue-500/10',
  completed: 'border-emerald-500/30 bg-emerald-500/10',
  failed: 'border-red-500/30 bg-red-500/10',
  interrupted: 'border-orange-500/30 bg-orange-500/10',
  cancelled: 'border-amber-500/30 bg-amber-500/10',
}
