import './global.css';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { Instrument_Sans, JetBrains_Mono, Orbitron } from 'next/font/google';
import type { ReactNode } from 'react';
import type { Metadata } from 'next';

const instrumentSans = Instrument_Sans({
  subsets: ['latin'],
  variable: '--font-instrument',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains',
});

const orbitron = Orbitron({
  weight: '700',
  subsets: ['latin'],
  variable: '--font-orbitron',
});

export const metadata: Metadata = {
  title: {
    template: '%s | Syntropic137',
    default: 'Syntropic137 - Agentic Engineering',
  },
  description:
    'Self-hosted agentic engineering platform. Run AI agents in isolated Docker workspaces with full observability. Every decision permanently captured.',
  icons: {
    icon: '/favicon.png',
    apple: '/favicon.png',
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      data-theme="syn137"
      className={`${instrumentSans.variable} ${jetbrainsMono.variable} ${orbitron.variable} font-sans`}
      suppressHydrationWarning
    >
      <body className="flex min-h-screen flex-col">
        <RootProvider
          theme={{
            defaultTheme: 'dark',
            attribute: 'class',
            enableSystem: true,
          }}
          search={{
            options: {
              type: 'static',
            },
          }}
        >
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
