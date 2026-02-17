import { source } from '@/lib/source';

export const revalidate = false;

export function GET() {
  const pages = source.getPages();
  const lines: string[] = [];

  for (const page of pages) {
    lines.push(`# ${page.data.title}`);
    lines.push(`URL: ${page.url}`);
    if (page.data.description) {
      lines.push('');
      lines.push(page.data.description);
    }
    lines.push('');
  }

  return new Response(lines.join('\n'));
}
