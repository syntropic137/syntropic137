import fs from 'node:fs';
import path from 'node:path';

function stripFrontmatter(content: string): string {
  const match = content.match(/^---\n[\s\S]*?\n---\n?/);
  return match ? content.slice(match[0].length).trim() : content.trim();
}

function stripJSX(content: string): string {
  let result = content;
  // Remove JSX comments {/* ... */}
  result = result.replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
  // Remove JSX tags with props (single and multi-line self-closing)
  result = result.replace(/<[A-Z][A-Za-z]*(?:\s[^]*?)?\/>/g, '');
  // Remove paired JSX tags
  result = result.replace(/<([A-Z][A-Za-z]*)(?:\s[^]*?)?>[^]*?<\/\1>/g, '');
  // Clean up excess whitespace
  result = result.replace(/\n{3,}/g, '\n\n');
  return result.trim();
}

function getTitle(content: string): { title?: string; description?: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const fm: Record<string, string> = {};
  for (const line of match[1].split('\n')) {
    if (/^\w/.test(line)) {
      const [key, ...rest] = line.split(':');
      if (key && rest.length) fm[key.trim()] = rest.join(':').trim();
    }
  }
  return { title: fm.title, description: fm.description };
}

interface Operation {
  path: string;
  method: string;
}

function extractAPIOperations(content: string): Operation[] | null {
  const match = content.match(/operations=\{(\[[\s\S]*?\])}/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]) as Operation[];
  } catch {
    return null;
  }
}

function renderOpenAPIPage(
  title: string | undefined,
  description: string | undefined,
  operations: Operation[],
  spec: Record<string, unknown>,
): string {
  const lines: string[] = [];
  if (title) lines.push(`# ${title}`);
  if (description) lines.push(`> ${description}`);
  lines.push('');

  const paths = spec.paths as Record<string, Record<string, Record<string, unknown>>> | undefined;
  if (!paths) return lines.join('\n');

  for (const op of operations) {
    const pathObj = paths[op.path];
    if (!pathObj) continue;
    const methodObj = pathObj[op.method];
    if (!methodObj) continue;

    const summary = methodObj.summary as string | undefined;
    const desc = methodObj.description as string | undefined;

    lines.push(`## ${summary || `${op.method.toUpperCase()} ${op.path}`}`);
    lines.push('');
    lines.push(`\`${op.method.toUpperCase()} ${op.path}\``);
    lines.push('');
    if (desc) {
      lines.push(desc);
      lines.push('');
    }

    // Parameters
    const params = methodObj.parameters as Array<Record<string, unknown>> | undefined;
    if (params && params.length > 0) {
      lines.push('**Parameters:**');
      for (const p of params) {
        const required = p.required ? ' (required)' : '';
        lines.push(`- \`${p.name}\` (${p.in})${required}: ${(p.schema as Record<string, unknown>)?.type || 'string'}`);
      }
      lines.push('');
    }

    // Request body
    const body = methodObj.requestBody as Record<string, unknown> | undefined;
    if (body) {
      const jsonContent = (body.content as Record<string, Record<string, unknown>>)?.['application/json'];
      if (jsonContent?.schema) {
        const schema = jsonContent.schema as Record<string, unknown>;
        const ref = schema.$ref as string | undefined;
        if (ref) {
          const schemaName = ref.split('/').pop();
          lines.push(`**Request Body:** \`${schemaName}\``);
        }
        lines.push('');
      }
    }

    // Response
    const responses = methodObj.responses as Record<string, Record<string, unknown>> | undefined;
    if (responses) {
      const successCode = Object.keys(responses).find(k => k.startsWith('2'));
      if (successCode) {
        const resp = responses[successCode];
        const jsonResp = (resp.content as Record<string, Record<string, unknown>> | undefined)?.['application/json'];
        if (jsonResp?.schema) {
          const schema = jsonResp.schema as Record<string, unknown>;
          const ref = schema.$ref as string | undefined;
          if (ref) {
            lines.push(`**Response (${successCode}):** \`${ref.split('/').pop()}\``);
          }
        }
      }
      lines.push('');
    }
  }

  return lines.join('\n');
}

let cachedSpec: Record<string, unknown> | null = null;

function getOpenAPISpec(): Record<string, unknown> {
  if (cachedSpec) return cachedSpec;
  const specPath = path.join(process.cwd(), 'openapi.json');
  cachedSpec = JSON.parse(fs.readFileSync(specPath, 'utf-8')) as Record<string, unknown>;
  return cachedSpec;
}

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
  const fm = getTitle(raw);

  // Check if this is an OpenAPI-generated page
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
