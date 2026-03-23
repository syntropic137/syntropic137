'use client';

import { Bot } from 'lucide-react';
import { SystemPromptSection, EndpointsGrid, UsageExamples } from './sections';

export default function LLMDocsPage() {
  return (
    <main className="flex-1">
      <div className="container mx-auto px-6 py-16 md:py-24 max-w-4xl">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <div className="p-3 rounded-lg bg-sky-500/15">
            <Bot className="w-8 h-8 text-sky-400" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-fd-foreground">LLM Documentation</h1>
            <p className="text-fd-muted-foreground">
              Get any AI agent up to speed on Syntropic137 in seconds
            </p>
          </div>
        </div>

        <div className="space-y-8">
          {/* Intro */}
          <p className="text-fd-muted-foreground text-lg">
            Syntropic137 provides machine-readable documentation endpoints so AI agents can
            quickly understand the entire platform. Copy a system prompt, fetch the full docs,
            or point your agent at the index.
          </p>

          <SystemPromptSection />
          <EndpointsGrid />
          <UsageExamples />
        </div>
      </div>
    </main>
  );
}
