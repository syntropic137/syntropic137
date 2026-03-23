'use client';

import Link from 'next/link';
import { FileText, Copy, Check, ExternalLink, BookOpen, Cpu } from 'lucide-react';
import { useState } from 'react';

function CopyButton({ text, label }: { text?: string; url?: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (text) {
        await navigator.clipboard.writeText(text);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
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

function FetchCopyButton({ url, label }: { url: string; label: string }) {
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

export const SYSTEM_PROMPT = `You are an expert on Syntropic137, an agentic engineering platform for orchestrating AI coding agents with event-sourced workflows.

## Quick Reference

- **Docs Index**: Fetch /llms.txt for a structured index of all documentation pages
- **Full Docs**: Fetch /llms-full.txt for complete documentation in a single file
- **API Reference**: 45+ REST endpoints at /api on port 8000
- **CLI**: The \`syn\` command-line tool for workflow management

## Architecture

Syntropic137 uses event sourcing + CQRS with four bounded contexts:
1. **Orchestration** — Workflows, Executions, Workspaces
2. **Agent Sessions** — Conversations, tool calls, token metrics
3. **GitHub Integration** — App installations, webhook triggers
4. **Artifacts** — Output storage with S3-compatible backend

## Key Commands

\`\`\`bash
# Start the platform
just api-dev

# Run a workflow
syn workflow run --name <workflow-name>

# View execution status
syn workflow status <execution-id>
\`\`\`

## Services

| Service | Port | Purpose |
|---------|------|---------|
| syn-api | 8000 | FastAPI REST API + WebSocket + SSE |
| event-store | 50051 | gRPC event sourcing server |
| event-collector | 8080 | High-throughput event ingestion |
| TimescaleDB | 5432 | Events and metrics storage |
| Redis | 6379 | Cache, pub/sub, projections |
| MinIO | 9000 | S3-compatible artifact storage |

When answering questions, reference the documentation. For API details, consult the full docs at /llms-full.txt.`;

export function SystemPromptSection() {
  return (
    <section className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Cpu className="w-5 h-5 text-sky-400" />
        <h2 className="text-xl font-semibold text-fd-foreground">Agent System Prompt</h2>
        <span className="text-xs px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-400 border border-sky-500/20">
          Recommended
        </span>
      </div>
      <p className="text-sm text-fd-muted-foreground">
        Drop this into any LLM system prompt to give it instant context on Syntropic137.
        Includes architecture overview, key commands, service ports, and pointers to full docs.
      </p>
      <div className="relative">
        <pre className="text-xs bg-zinc-950 rounded-lg p-4 overflow-x-auto max-h-64 overflow-y-auto border border-zinc-800">
          <code className="text-zinc-300 whitespace-pre-wrap">{SYSTEM_PROMPT}</code>
        </pre>
      </div>
      <CopyButton text={SYSTEM_PROMPT} label="Copy system prompt" />
    </section>
  );
}

export function EndpointsGrid() {
  return (
    <div className="grid md:grid-cols-2 gap-6">
      {/* llms.txt */}
      <section className="rounded-lg border border-fd-border p-6 space-y-3">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-sky-400" />
          <h2 className="text-lg font-semibold text-fd-foreground">llms.txt</h2>
        </div>
        <p className="text-xs px-2 py-0.5 rounded-full bg-zinc-500/15 text-zinc-400 border border-zinc-500/20 inline-block">
          Structured Index
        </p>
        <p className="text-sm text-fd-muted-foreground">
          Concise index of all documentation pages with titles, URLs, and descriptions.
          Point an agent here first for navigation.
        </p>
        <div className="flex flex-wrap gap-2">
          <FetchCopyButton url="/llms.txt" label="Copy" />
          <Link
            href="/llms.txt"
            target="_blank"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-sky-500/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
          >
            <ExternalLink className="w-4 h-4" />
            View
          </Link>
        </div>
      </section>

      {/* llms-full.txt */}
      <section className="rounded-lg border border-fd-border p-6 space-y-3">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-sky-400" />
          <h2 className="text-lg font-semibold text-fd-foreground">llms-full.txt</h2>
        </div>
        <p className="text-xs px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-400 border border-sky-500/20 inline-block">
          Full Content
        </p>
        <p className="text-sm text-fd-muted-foreground">
          Every documentation page concatenated into one file.
          Complete platform knowledge in a single fetch.
        </p>
        <div className="flex flex-wrap gap-2">
          <FetchCopyButton url="/llms-full.txt" label="Copy" />
          <Link
            href="/llms-full.txt"
            target="_blank"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-sky-500/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
          >
            <ExternalLink className="w-4 h-4" />
            View
          </Link>
        </div>
      </section>
    </div>
  );
}

export function UsageExamples() {
  return (
    <section className="rounded-lg border border-fd-border p-6 space-y-4">
      <h2 className="text-lg font-semibold text-fd-foreground">Usage</h2>

      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-medium text-fd-foreground mb-2">Claude Code / CLAUDE.md</h3>
          <pre className="text-sm bg-zinc-950 rounded-lg p-4 overflow-x-auto border border-zinc-800">
            <code className="text-zinc-300">{`# In your CLAUDE.md or system prompt:
Fetch https://docs.syntropic137.com/llms-full.txt for complete Syntropic137 docs.`}</code>
          </pre>
        </div>

        <div>
          <h3 className="text-sm font-medium text-fd-foreground mb-2">curl / CLI</h3>
          <pre className="text-sm bg-zinc-950 rounded-lg p-4 overflow-x-auto border border-zinc-800">
            <code className="text-zinc-300">{`# Index only
curl -s https://docs.syntropic137.com/llms.txt

# Full documentation
curl -s https://docs.syntropic137.com/llms-full.txt

# Pipe directly to clipboard
curl -s https://docs.syntropic137.com/llms-full.txt | pbcopy`}</code>
          </pre>
        </div>

        <div>
          <h3 className="text-sm font-medium text-fd-foreground mb-2">MCP / Tool Use</h3>
          <pre className="text-sm bg-zinc-950 rounded-lg p-4 overflow-x-auto border border-zinc-800">
            <code className="text-zinc-300">{`// Use WebFetch to give an agent full context
const docs = await fetch("https://docs.syntropic137.com/llms-full.txt");
const text = await docs.text();
// Include in system prompt or tool response`}</code>
          </pre>
        </div>
      </div>
    </section>
  );
}
