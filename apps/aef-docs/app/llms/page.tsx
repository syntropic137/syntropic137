'use client';

import Link from 'next/link';
import { Bot, FileText, Copy, Check, ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { baseOptions } from '@/lib/layout.shared';

function CopyButton({ url, label }: { url: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      const res = await fetch(url);
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.open(url, '_blank');
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-sky-500/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
    >
      {copied ? <Check className="w-4 h-4 text-teal-400" /> : <Copy className="w-4 h-4" />}
      {copied ? 'Copied!' : label}
    </button>
  );
}

export default function LLMDocsPage() {
  return (
    <main className="flex-1">
      <div className="container mx-auto px-6 py-16 md:py-24 max-w-3xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 rounded-lg bg-sky-500/15">
            <Bot className="w-8 h-8 text-sky-400" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-fd-foreground">LLM Docs</h1>
            <p className="text-fd-muted-foreground">Machine-readable documentation for AI agents</p>
          </div>
        </div>

        <div className="space-y-6">
          <p className="text-fd-muted-foreground">
            Syntropic137 provides structured documentation endpoints optimized for consumption by
            large language models. Use these to give AI agents full context about the platform.
          </p>

          {/* llms.txt */}
          <div className="rounded-lg border border-fd-border p-6 space-y-3">
            <div className="flex items-center gap-2">
              <FileText className="w-5 h-5 text-sky-400" />
              <h2 className="text-lg font-semibold text-fd-foreground">llms.txt</h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-400 border border-sky-500/20">
                Structured Index
              </span>
            </div>
            <p className="text-sm text-fd-muted-foreground">
              A concise index of all documentation pages with titles, URLs, and descriptions.
              Ideal for giving an LLM an overview of available documentation.
            </p>
            <div className="flex gap-3">
              <CopyButton url="/llms.txt" label="Copy to clipboard" />
              <Link
                href="/llms.txt"
                target="_blank"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-sky-500/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
              >
                <ExternalLink className="w-4 h-4" />
                View raw
              </Link>
            </div>
          </div>

          {/* llms-full.txt */}
          <div className="rounded-lg border border-fd-border p-6 space-y-3">
            <div className="flex items-center gap-2">
              <FileText className="w-5 h-5 text-sky-400" />
              <h2 className="text-lg font-semibold text-fd-foreground">llms-full.txt</h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-500/15 text-zinc-400 border border-zinc-500/20">
                Full Content
              </span>
            </div>
            <p className="text-sm text-fd-muted-foreground">
              The complete documentation content concatenated into a single file.
              Use this when you need the LLM to have deep knowledge of the entire platform.
            </p>
            <div className="flex gap-3">
              <CopyButton url="/llms-full.txt" label="Copy to clipboard" />
              <Link
                href="/llms-full.txt"
                target="_blank"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-sky-500/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
              >
                <ExternalLink className="w-4 h-4" />
                View raw
              </Link>
            </div>
          </div>

          {/* Usage */}
          <div className="rounded-lg border border-fd-border p-6 space-y-3">
            <h2 className="text-lg font-semibold text-fd-foreground">Usage</h2>
            <p className="text-sm text-fd-muted-foreground">
              Pass these URLs to any LLM context window or system prompt:
            </p>
            <pre className="text-sm bg-zinc-900 rounded-lg p-4 overflow-x-auto">
              <code className="text-sky-300">{`# Quick overview\ncurl https://your-domain.com/llms.txt\n\n# Full documentation\ncurl https://your-domain.com/llms-full.txt`}</code>
            </pre>
          </div>
        </div>
      </div>
    </main>
  );
}
