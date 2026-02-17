import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import Image from 'next/image';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <div className="flex items-center gap-2.5">
          <Image
            src="/logo-dark.svg"
            alt="AEF"
            width={28}
            height={28}
            className="hidden dark:block"
          />
          <Image
            src="/logo-light.svg"
            alt="AEF"
            width={28}
            height={28}
            className="block dark:hidden"
          />
          <span className="font-semibold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent dark:from-indigo-300 dark:to-purple-300 inline-block leading-normal">
            AEF
          </span>
        </div>
      ),
    },
    links: [],
    githubUrl: 'https://github.com/AgentParadise/agentic-engineering-framework',
  };
}
