import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import Image from 'next/image';
import packageJson from '../package.json';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <div className="flex items-center gap-2.5">
          <Image
            src="/logo.png"
            alt="Syntropic137"
            width={28}
            height={28}
          />
          <div className="flex flex-col leading-none">
            <span className="font-bold text-sm tracking-wider text-fd-primary" style={{ fontFamily: 'var(--font-orbitron), sans-serif' }}>
              Syntropic137
            </span>
            <span className="text-[10px] text-fd-muted-foreground tracking-wide uppercase">
              Agentic Engineering
            </span>
          </div>
        </div>
      ),
    },
    links: [
      {
        text: `v${packageJson.version}`,
        url: `https://github.com/syntropic137/syntropic137/releases/tag/v${packageJson.version}`,
      },
    ],
    githubUrl: 'https://github.com/syntropic137/syntropic137',
  };
}
