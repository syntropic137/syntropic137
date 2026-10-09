'use client';

import { useState } from 'react';
import Link from 'next/link';
import { FileText, Copy, Check, Pencil } from 'lucide-react';

export function LLMCopyButton({ content, title, editUrl, mdUrl }: { content: string; title: string; editUrl?: string; mdUrl: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      const text = `# ${title}\n\n${content}`;
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  return (
    <div className="syn-llm-actions not-prose">
      <button
        onClick={handleCopy}
        type="button"
        className="syn-llm-action"
        data-variant="control"
        data-state={copied ? 'copied' : undefined}
      >
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {copied ? 'Copied for LLM' : 'Copy for LLM'}
      </button>
      <Link
        href={mdUrl}
        target="_blank"
        className="syn-llm-action"
      >
        <FileText aria-hidden="true" />
        View as Markdown
      </Link>
      {editUrl && (
        <Link
          href={editUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="syn-llm-action"
        >
          <Pencil aria-hidden="true" />
          Edit on GitHub
        </Link>
      )}
    </div>
  );
}
