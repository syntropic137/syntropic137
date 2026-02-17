import { source } from '@/lib/source';

export const revalidate = false;

export function GET() {
  const lines: string[] = [];
  lines.push('# Syntropic137 Documentation');
  lines.push('');
  lines.push('> Syntropic137 — Agentic Engineering. Orchestrate AI agents with event-sourced workflows.');
  lines.push('');
  lines.push('## Endpoints');
  lines.push('');
  lines.push('- /llms.txt — This file. Structured index of all documentation pages.');
  lines.push('- /llms-full.txt — Complete documentation content in a single file.');
  lines.push('');
  lines.push('## Pages');
  lines.push('');

  for (const page of source.getPages()) {
    lines.push(
      `- [${page.data.title}](${page.url})${page.data.description ? `: ${page.data.description}` : ''}`,
    );
  }

  return new Response(lines.join('\n'), {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
