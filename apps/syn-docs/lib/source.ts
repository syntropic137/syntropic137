import { docs } from '@/.source/server';
import { type InferPageType, loader } from 'fumadocs-core/source';
import { createOpenAPI } from 'fumadocs-openapi/server';
import { createAPIPage } from 'fumadocs-openapi/ui';

export const source = loader({
  baseUrl: '/docs',
  source: docs.toFumadocsSource(),
});

export const openapi = createOpenAPI({
  input: ['./openapi.json'],
});

export const APIPage = createAPIPage(openapi);

export type Page = InferPageType<typeof source>;

export function getLLMText(page: Page): string {
  return `# ${page.data.title}

URL: ${page.url}
${page.data.description ? `\n${page.data.description}\n` : ''}`;
}
