import { Clipboard, Check, ExternalLink } from 'lucide-react'
import { useState, useCallback } from 'react'
import type { OperationInfo } from '../../types'

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard unavailable in non-secure contexts
    }
  }, [text])

  return (
    <button
      onClick={handleCopy}
      title={`Copy ${label}`}
      className="flex items-center gap-1 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Clipboard className="h-3 w-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function DetailBlock({ label, content, mono = false, maxHeight = true }: {
  label: string
  content: string
  mono?: boolean
  maxHeight?: boolean
}) {
  return (
    <div className="mb-2">
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium text-[var(--color-text-secondary)]">{label}</span>
        <CopyButton text={content} label={label.replace(':', '')} />
      </div>
      <pre className={`${maxHeight ? 'max-h-48' : ''} overflow-auto whitespace-pre-wrap rounded-md bg-[var(--color-background)] border border-[var(--color-border)] p-2 text-[var(--color-text-muted)] ${mono ? 'font-mono' : ''}`}>
        {content}
      </pre>
    </div>
  )
}

function buildGitHubCommitUrl(repo: string, sha: string): string | null {
  // repo is "owner/repo" format
  if (!repo.includes('/')) return null
  return `https://github.com/${repo}/commit/${sha}`
}

function GitDetails({ op }: { op: OperationInfo }) {
  // Only show expanded details if there's a commit message or GitHub link.
  // SHA/branch/repo are already shown in the sub-header badges (GitOperationMeta).
  if (!op.git_message) return null

  const commitUrl = op.git_repo && op.git_sha
    ? buildGitHubCommitUrl(op.git_repo, op.git_sha)
    : null

  return (
    <div className="mb-2">
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium text-[var(--color-text-secondary)]">Commit:</span>
        <div className="flex items-center gap-3">
          {commitUrl && (
            <a
              href={commitUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[var(--color-text-muted)] hover:text-orange-400 transition-colors"
            >
              <ExternalLink className="h-3 w-3" />
              View on GitHub
            </a>
          )}
          <CopyButton text={op.git_message} label="commit message" />
        </div>
      </div>

      <pre className="whitespace-pre-wrap rounded-md bg-[var(--color-background)] border border-[var(--color-border)] p-2 text-[var(--color-text-muted)] font-mono">
        {op.git_message}
      </pre>
    </div>
  )
}

export function OperationDetails({ op }: { op: OperationInfo }) {
  const hasGitDetails = !!op.git_message

  return (
    <div className="mt-2 rounded-lg bg-[var(--color-surface)] p-3 text-xs">
      {hasGitDetails && <GitDetails op={op} />}
      {op.tool_input && <DetailBlock label="Input:" content={JSON.stringify(op.tool_input, null, 2)} mono maxHeight={false} />}
      {op.tool_output && <DetailBlock label="Output:" content={op.tool_output} mono />}
      {op.message_content && <DetailBlock label={`Message (${op.message_role}):`} content={op.message_content} />}
      {op.thinking_content && <DetailBlock label="Thinking:" content={op.thinking_content} />}
    </div>
  )
}
