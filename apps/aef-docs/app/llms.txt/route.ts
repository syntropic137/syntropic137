import { source } from '@/lib/source';

export const revalidate = false;

export function GET() {
  const lines: string[] = [];
  lines.push('# AEF Documentation');
  lines.push('');
  lines.push('> Agentic Engineering Framework — orchestrate AI agents with event-sourced workflows.');
  lines.push('');

  for (const page of source.getPages()) {
    lines.push(
      `- [${page.data.title}](${page.url})${page.data.description ? `: ${page.data.description}` : ''}`,
    );
  }

  return new Response(lines.join('\n'));
}
