import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  async redirects() {
    return [
      {
        source: '/docs',
        destination: '/docs/guide/getting-started',
        permanent: false,
      },
      {
        // The Claude Code plugin page became the agent skills page.
        source: '/docs/guide/claude-code-plugin',
        destination: '/docs/guide/agent-skills',
        permanent: true,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: '/docs/:path*.txt',
        destination: '/api/docs-txt/:path*',
      },
      {
        source: '/docs.txt',
        destination: '/api/docs-txt/index',
      },
      {
        source: '/docs/:path*.md',
        destination: '/api/docs-txt/:path*',
      },
      {
        source: '/docs.md',
        destination: '/api/docs-txt/index',
      },
      {
        source: '/llms.md',
        destination: '/llms.txt',
      },
      {
        source: '/llms-full.md',
        destination: '/llms-full.txt',
      },
    ];
  },
};

export default withMDX(config);
