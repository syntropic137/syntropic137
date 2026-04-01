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
    <div className="flex items-center gap-2 mb-4 not-prose">
      <button
        onClick={handleCopy}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-zinc-700 hover:border-fd-primary/30 text-fd-muted-foreground hover:text-fd-foreground hover:bg-zinc-800/50 transition-all"
      >
        {copied ? <Check className="w-3.5 h-3.5 text-teal-400" /> : <Copy className="w-3.5 h-3.5" />}
        {copied ? 'Copied for LLM' : 'Copy for LLM'}
      </button>
      <Link
        href={mdUrl}
        target="_blank"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-fd-muted-foreground hover:text-fd-primary transition-colors"
      >
        <FileText className="w-3.5 h-3.5" />
        View as Markdown
      </Link>
      {editUrl && (
        <Link
          href={editUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-fd-muted-foreground hover:text-fd-primary transition-colors"
        >
          <Pencil className="w-3.5 h-3.5" />
          Edit on GitHub
        </Link>
      )}
    </div>
  );
}
