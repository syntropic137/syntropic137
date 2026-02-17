import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import Image from 'next/image';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <div className="flex items-center gap-2.5">
          <Image
            src="/logo-dark.svg"
            alt="Syntropic137"
            width={28}
            height={28}
            className="hidden dark:block"
          />
          <Image
            src="/logo-light.svg"
            alt="Syntropic137"
            width={28}
            height={28}
            className="block dark:hidden"
          />
          <div className="flex flex-col leading-none">
            <span className="font-bold text-sm tracking-tight text-fd-foreground">
              Syntropic<span className="text-sky-400">137</span>
            </span>
            <span className="text-[10px] text-fd-muted-foreground tracking-wide uppercase">
              Agentic Engineering
            </span>
          </div>
        </div>
      ),
    },
    links: [],
    githubUrl: 'https://github.com/AgentParadise/agentic-engineering-framework',
  };
}
