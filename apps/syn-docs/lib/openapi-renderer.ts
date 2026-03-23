import fs from 'node:fs';
import path from 'node:path';
import { renderParameters, renderRequestBody, renderResponses } from './openapi-sections';

export interface Operation {
  path: string;
  method: string;
}

export function extractAPIOperations(content: string): Operation[] | null {
  const match = content.match(/operations=\{(\[[\s\S]*?\])}/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]) as Operation[];
  } catch {
    return null;
  }
}

let cachedSpec: Record<string, unknown> | null = null;

export function getOpenAPISpec(): Record<string, unknown> {
  if (cachedSpec) return cachedSpec;
  const specPath = path.join(process.cwd(), 'openapi.json');
  cachedSpec = JSON.parse(fs.readFileSync(specPath, 'utf-8')) as Record<string, unknown>;
  return cachedSpec;
}

function renderOperation(op: Operation, methodObj: Record<string, unknown>): string[] {
  const lines: string[] = [];
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

  const params = methodObj.parameters as Array<Record<string, unknown>> | undefined;
  if (params && params.length > 0) {
    lines.push(...renderParameters(params));
    lines.push('');
  }

  const body = methodObj.requestBody as Record<string, unknown> | undefined;
  if (body) lines.push(...renderRequestBody(body));

  const responses = methodObj.responses as Record<string, Record<string, unknown>> | undefined;
  if (responses) {
    lines.push(...renderResponses(responses));
    lines.push('');
  }

  return lines;
}

export function renderOpenAPIPage(
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
    const methodObj = paths[op.path]?.[op.method];
    if (!methodObj) continue;
    lines.push(...renderOperation(op, methodObj));
  }

  return lines.join('\n');
}
