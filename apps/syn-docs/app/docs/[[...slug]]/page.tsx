import fs from 'node:fs';
import path from 'node:path';
import { source } from '@/lib/source';
import {
  DocsPage,
  DocsBody,
  DocsTitle,
  DocsDescription,
} from 'fumadocs-ui/page';
import { notFound } from 'next/navigation';
import { getMDXComponents } from '@/mdx-components';
import { LLMCopyButton } from '@/components/LLMCopyButton';
import { DocsFooter } from '@/components/DocsFooter';

function getRawContent(slug?: string[]): string {
  const contentDir = path.join(process.cwd(), 'content/docs');

  if (!slug || slug.length === 0) {
    const indexPath = path.join(contentDir, 'index.mdx');
    if (fs.existsSync(indexPath)) return stripFrontmatterAndJSX(fs.readFileSync(indexPath, 'utf-8'));
    return '';
  }

  const slugPath = slug.join('/');
  // Try direct file first, then index in folder
  for (const candidate of [`${slugPath}.mdx`, `${slugPath}/index.mdx`]) {
    const full = path.join(contentDir, candidate);
    if (fs.existsSync(full)) return stripFrontmatterAndJSX(fs.readFileSync(full, 'utf-8'));
  }
  return '';
}

function getEditUrl(slug?: string[]): string {
  const branch = process.env.NEXT_PUBLIC_EDIT_BRANCH || 'main';
  const base = `https://github.com/syntropic137/syntropic137/edit/${branch}/apps/syn-docs/content/docs`;
  if (!slug || slug.length === 0) return `${base}/index.mdx`;

  const slugPath = slug.join('/');
  const contentDir = path.join(process.cwd(), 'content/docs');
  // Check if it's a direct file or folder with index
  if (fs.existsSync(path.join(contentDir, `${slugPath}.mdx`))) return `${base}/${slugPath}.mdx`;
  if (fs.existsSync(path.join(contentDir, `${slugPath}/index.mdx`))) return `${base}/${slugPath}/index.mdx`;
  return `${base}/${slugPath}.mdx`;
}

function stripFrontmatterAndJSX(content: string): string {
  let result = content.replace(/^---\n[\s\S]*?\n---\n/, '').trim();
  result = result.replace(/<[A-Z][A-Za-z]+ \/>/g, '');
  result = result.replace(/\n{3,}/g, '\n\n');
  return result;
}

export default async function Page(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  const MDXContent = page.data.body;
  const rawContent = getRawContent(params.slug);
  const editUrl = getEditUrl(params.slug);
  const mdUrl = params.slug ? `/docs/${params.slug.join('/')}.md` : '/docs.md';

  return (
    <DocsPage toc={page.data.toc}>
      <DocsTitle>{page.data.title}</DocsTitle>
      <DocsDescription>{page.data.description}</DocsDescription>
      <LLMCopyButton content={rawContent} title={page.data.title} editUrl={editUrl} mdUrl={mdUrl} />
      <DocsBody>
        <MDXContent
          components={getMDXComponents({})}
        />
      </DocsBody>
      <DocsFooter />
    </DocsPage>
  );
}

export function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  return {
    title: page.data.title,
    description: page.data.description,
  };
}
