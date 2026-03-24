export function renderParameters(params: Array<Record<string, unknown>>): string[] {
  const lines: string[] = ['**Parameters:**'];
  for (const p of params) {
    const required = p.required ? ' (required)' : '';
    lines.push(`- \`${p.name}\` (${p.in})${required}: ${(p.schema as Record<string, unknown>)?.type || 'string'}`);
  }
  return lines;
}

export function renderRequestBody(body: Record<string, unknown>): string[] {
  const jsonContent = (body.content as Record<string, Record<string, unknown>>)?.['application/json'];
  if (!jsonContent?.schema) return [];
  const schema = jsonContent.schema as Record<string, unknown>;
  const ref = schema.$ref as string | undefined;
  if (!ref) return [''];
  return [`**Request Body:** \`${ref.split('/').pop()}\``, ''];
}

export function renderResponses(responses: Record<string, Record<string, unknown>>): string[] {
  const successCode = Object.keys(responses).find(k => k.startsWith('2'));
  if (!successCode) return [];
  const resp = responses[successCode];
  const jsonResp = (resp.content as Record<string, Record<string, unknown>> | undefined)?.['application/json'];
  if (!jsonResp?.schema) return [];
  const schema = jsonResp.schema as Record<string, unknown>;
  const ref = schema.$ref as string | undefined;
  if (!ref) return [];
  return [`**Response (${successCode}):** \`${ref.split('/').pop()}\``];
}
