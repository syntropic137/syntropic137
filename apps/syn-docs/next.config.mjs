import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
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
    ];
  },
};

export default withMDX(config);
