import './global.css';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { Inter, JetBrains_Mono, Orbitron } from 'next/font/google';
import type { ReactNode } from 'react';
import type { Metadata } from 'next';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
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
    default: 'Syntropic137 — Agentic Engineering',
  },
  description:
    'Orchestrate AI agents with event-sourced workflows. Build, observe, and scale agentic systems with precision.',
  icons: {
    icon: '/favicon.svg',
    apple: '/favicon.svg',
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} ${orbitron.variable} ${inter.className}`} suppressHydrationWarning>
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
