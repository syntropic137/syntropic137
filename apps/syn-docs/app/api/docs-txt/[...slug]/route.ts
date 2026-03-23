import fs from 'node:fs';
import path from 'node:path';
import { stripFrontmatter, stripJSX, parseFrontmatter } from '@/lib/mdx-text';
import { extractAPIOperations, getOpenAPISpec, renderOpenAPIPage } from '@/lib/openapi-renderer';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string[] }> },
) {
  const { slug } = await params;
  const contentDir = path.join(process.cwd(), 'content/docs');
  const slugPath = slug.join('/');

  let filePath: string | null = null;
  for (const candidate of [`${slugPath}.mdx`, `${slugPath}/index.mdx`]) {
    const full = path.join(contentDir, candidate);
    if (fs.existsSync(full)) {
      filePath = full;
      break;
    }
  }

  if (!filePath) {
    return new Response('Not found', { status: 404 });
  }

  const raw = fs.readFileSync(filePath, 'utf-8');
  const fm = parseFrontmatter(raw);

  const operations = extractAPIOperations(raw);
  let output: string;

  if (operations) {
    const spec = getOpenAPISpec();
    output = renderOpenAPIPage(fm.title, fm.description, operations, spec);
  } else {
    const body = stripJSX(stripFrontmatter(raw));
    const lines: string[] = [];
    if (fm.title) lines.push(`# ${fm.title}`);
    if (fm.description) lines.push(`> ${fm.description}`);
    if (fm.title || fm.description) lines.push('');
    lines.push(body);
    output = lines.join('\n');
  }

  return new Response(output, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
