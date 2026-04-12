import { Terminal } from 'lucide-react'

export function CliDisclaimerBanner() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-blue-500/20 bg-blue-500/10 px-4 py-3">
      <Terminal className="h-4 w-4 shrink-0 text-blue-400 mt-0.5" />
      <p className="text-sm text-blue-300">
        This page is intended to be operated by an agent through the CLI, either locally or remotely.
        Manual kickoff is available as a convenience if desired.
      </p>
    </div>
  )
}
