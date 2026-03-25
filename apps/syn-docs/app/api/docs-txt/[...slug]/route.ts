import fs from 'node:fs';
import path from 'node:path';
import { stripFrontmatter, stripJSX, parseFrontmatter } from '@/lib/mdx-text';
import { extractAPIOperations, getOpenAPISpec, renderOpenAPIPage } from '@/lib/openapi-renderer';

function resolveFilePath(contentDir: string, slugPath: string): string | null {
  for (const candidate of [`${slugPath}.mdx`, `${slugPath}/index.mdx`]) {
    const full = path.join(contentDir, candidate);
    if (fs.existsSync(full)) return full;
  }
  return null;
}

function renderMarkdownPage(raw: string): string {
  const fm = parseFrontmatter(raw);
  const operations = extractAPIOperations(raw);
  if (operations) {
    const spec = getOpenAPISpec();
    return renderOpenAPIPage(fm.title, fm.description, operations, spec);
  }
  const body = stripJSX(stripFrontmatter(raw));
  const lines: string[] = [];
  if (fm.title) lines.push(`# ${fm.title}`);
  if (fm.description) lines.push(`> ${fm.description}`);
  if (fm.title || fm.description) lines.push('');
  lines.push(body);
  return lines.join('\n');
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string[] }> },
) {
  const { slug } = await params;
  const contentDir = path.join(process.cwd(), 'content/docs');
  const filePath = resolveFilePath(contentDir, slug.join('/'));

  if (!filePath) {
    return new Response('Not found', { status: 404 });
  }

  const raw = fs.readFileSync(filePath, 'utf-8');
  const output = renderMarkdownPage(raw);

  return new Response(output, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
