import { source } from '@/lib/source';
import { type NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

export function GET(request: NextRequest) {
  const origin = request.nextUrl.origin;
  const lines: string[] = [];

  lines.push('# Syntropic137 Documentation');
  lines.push('');
  lines.push('> Syntropic137 — Agentic Engineering Platform. Orchestrate AI agents with event-sourced workflows.');
  lines.push('');
  lines.push('## LLM Endpoints');
  lines.push('');
  lines.push(`- ${origin}/llms.md — This file. Structured index of all documentation pages.`);
  lines.push(`- ${origin}/llms-full.md — Complete documentation content in a single file.`);
  lines.push(`- ${origin}/llms — Human-readable LLM docs page with system prompt and usage guide.`);
  lines.push('');
  lines.push('## Pages');
  lines.push('');

  for (const page of source.getPages()) {
    lines.push(
      `- [${page.data.title}](${origin}${page.url})${page.data.description ? `: ${page.data.description}` : ''}`,
    );
  }

  lines.push('');
  lines.push('## Markdown Endpoints');
  lines.push('');
  lines.push('Each page is available as raw MDX at its `.md` URL (for agents and LLMs):');
  lines.push('');

  for (const page of source.getPages()) {
    lines.push(`- [${page.data.title}](${origin}${page.url}.md)`);
  }

  return new Response(lines.join('\n'), {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
