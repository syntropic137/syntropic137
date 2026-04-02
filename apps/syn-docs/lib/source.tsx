import { docs } from '@/.source/server';
import { type InferPageType, loader } from 'fumadocs-core/source';
import { createOpenAPI } from 'fumadocs-openapi/server';
import { createAPIPage, type ApiPageProps } from 'fumadocs-openapi/ui';

export const source = loader({
  baseUrl: '/docs',
  source: docs.toFumadocsSource(),
});

export const openapi = createOpenAPI({
  input: ['./openapi.json'],
});

const BaseAPIPage = createAPIPage(openapi);

/**
 * Wraps fumadocs-openapi's APIPage with scoping + parameter spacing.
 * Inline <style> bypasses Tailwind v4's PostCSS pipeline which rewrites
 * selectors referencing utility class names like .py-4 in global.css.
 */
export function APIPage(props: ApiPageProps) {
  return (
    <div className="api-reference">
      <style>{`
        .api-reference .border-t { padding-top: 1.25rem; padding-bottom: 1.25rem; }
        .api-reference .border-t:first-child { padding-top: 0; }
      `}</style>
      <BaseAPIPage {...props} />
    </div>
  );
}

export type Page = InferPageType<typeof source>;

export function getLLMText(page: Page): string {
  return `# ${page.data.title}

URL: ${page.url}
${page.data.description ? `\n${page.data.description}\n` : ''}`;
}
