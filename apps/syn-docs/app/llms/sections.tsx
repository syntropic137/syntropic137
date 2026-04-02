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
      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-fd-primary/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
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
      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-fd-primary/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
    >
      {copied ? <Check className="w-4 h-4 text-teal-400" /> : <Copy className="w-4 h-4" />}
      {copied ? 'Copied!' : label}
    </button>
  );
}

export const SYSTEM_PROMPT = `You are an expert on Syntropic137, an agentic engineering platform for orchestrating AI coding agents with event-sourced workflows.

## Quick Reference

- **Docs Index**: Fetch /llms.md for a structured index of all documentation pages
- **Full Docs**: Fetch /llms-full.md for complete documentation in a single file
- **API Reference**: REST endpoints at /api — accessible via gateway on port 8137
- **CLI**: The \`syn\` command-line tool for workflow management
- **Setup CLI**: \`npx @syntropic137/setup\` for installation and platform management

## Architecture

Syntropic137 uses event sourcing + CQRS with five bounded contexts:
1. **Orchestration** — Workflows, Executions, Workspaces
2. **Agent Sessions** — Conversations, tool calls, token metrics
3. **GitHub Integration** — App installations, webhook triggers, hybrid event pipeline
4. **Artifacts** — Output storage with S3-compatible backend
5. **Organization** — Organizations, Systems, Repos — hierarchy for cost rollup and health monitoring

## Key Commands

\`\`\`bash
# Install and start the platform
npx @syntropic137/setup init

# Manage the running stack
npx @syntropic137/setup status
npx @syntropic137/setup start
npx @syntropic137/setup stop

# Run a workflow
syn workflow run <workflow-id> --task "Your task here"

# View workflow run history
syn workflow status <workflow-id>

# Install a workflow package
syn workflow install ./my-package/
syn workflow install org/repo
\`\`\`

## Services

| Service | Port | Purpose |
|---------|------|---------|
| gateway | 8137 | nginx reverse proxy + dashboard UI (primary access point) |
| syn-api | 8000 | FastAPI REST API + WebSocket + SSE (internal — access through gateway) |
| event-store | 50051 | gRPC event sourcing server |
| event-collector | 8080 | High-throughput event ingestion |
| TimescaleDB | 5432 | Events and metrics storage |
| Redis | 6379 | Cache, pub/sub, projections |
| MinIO | 9000 | S3-compatible artifact storage |

## Guide Topics

- **Getting Started** — install and first workflow in 5 minutes
- **Core Concepts** — events, workspaces, workflows, observability mental model
- **Workflow Packages** — create, install, and distribute pre-built workflows
- **Claude Code Plugin** — /syn-* slash commands and domain skills
- **GitHub Integration** — webhook triggers and automated workflows
- **Plugins** — distributable workflow bundles from GitHub repos
- **Self-Hosting** — deploy on your own infrastructure
- **Configuration** — environment variables and GitHub App setup
- **Tunnels** — expose the platform for webhooks and remote access
- **Secrets Management** — file-based secrets and 1Password integration
- **Event Ingestion** — hybrid webhook + polling pipeline

When answering questions, reference the documentation. For API details, consult the full docs at /llms-full.md.`;

export function SystemPromptSection() {
  return (
    <section className="rounded-lg border border-fd-primary/20 bg-fd-primary/5 p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Cpu className="w-5 h-5 text-fd-primary" />
        <h2 className="text-xl font-semibold text-fd-foreground">Agent System Prompt</h2>
        <span className="text-xs px-2 py-0.5 rounded-full bg-fd-primary/15 text-fd-primary border border-fd-primary/20">
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
      {/* llms.md */}
      <section className="rounded-lg border border-fd-border p-6 space-y-3">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-fd-primary" />
          <h2 className="text-lg font-semibold text-fd-foreground">llms.md</h2>
        </div>
        <p className="text-xs px-2 py-0.5 rounded-full bg-zinc-500/15 text-zinc-400 border border-zinc-500/20 inline-block">
          Structured Index
        </p>
        <p className="text-sm text-fd-muted-foreground">
          Concise index of all documentation pages with titles, URLs, and descriptions.
          Point an agent here first for navigation.
        </p>
        <div className="flex flex-wrap gap-2">
          <FetchCopyButton url="/llms.md" label="Copy" />
          <Link
            href="/llms.md"
            target="_blank"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-fd-primary/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
          >
            <ExternalLink className="w-4 h-4" />
            View
          </Link>
        </div>
      </section>

      {/* llms-full.md */}
      <section className="rounded-lg border border-fd-border p-6 space-y-3">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-fd-primary" />
          <h2 className="text-lg font-semibold text-fd-foreground">llms-full.md</h2>
        </div>
        <p className="text-xs px-2 py-0.5 rounded-full bg-fd-primary/15 text-fd-primary border border-fd-primary/20 inline-block">
          Full Content
        </p>
        <p className="text-sm text-fd-muted-foreground">
          Every documentation page concatenated into one file.
          Complete platform knowledge in a single fetch.
        </p>
        <div className="flex flex-wrap gap-2">
          <FetchCopyButton url="/llms-full.md" label="Copy" />
          <Link
            href="/llms-full.md"
            target="_blank"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-zinc-700 hover:border-fd-primary/30 text-fd-foreground hover:bg-zinc-800/50 transition-all"
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
Fetch https://docs.syntropic137.com/llms-full.md for complete Syntropic137 docs.`}</code>
          </pre>
        </div>

        <div>
          <h3 className="text-sm font-medium text-fd-foreground mb-2">curl / CLI</h3>
          <pre className="text-sm bg-zinc-950 rounded-lg p-4 overflow-x-auto border border-zinc-800">
            <code className="text-zinc-300">{`# Index only
curl -s https://docs.syntropic137.com/llms.md

# Full documentation
curl -s https://docs.syntropic137.com/llms-full.md

# Pipe directly to clipboard
curl -s https://docs.syntropic137.com/llms-full.md | pbcopy`}</code>
          </pre>
        </div>

        <div>
          <h3 className="text-sm font-medium text-fd-foreground mb-2">MCP / Tool Use</h3>
          <pre className="text-sm bg-zinc-950 rounded-lg p-4 overflow-x-auto border border-zinc-800">
            <code className="text-zinc-300">{`// Use WebFetch to give an agent full context
const docs = await fetch("https://docs.syntropic137.com/llms-full.md");
const text = await docs.text();
// Include in system prompt or tool response`}</code>
          </pre>
        </div>
      </div>
    </section>
  );
}
