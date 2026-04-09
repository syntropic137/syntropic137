'use client';

import Link from 'next/link';
import { ArrowRight, BookOpen, Rocket, Terminal, Workflow, Eye, Zap, GitBranch, Bot, Github, Twitter } from 'lucide-react';

function QuickLink({
  href,
  icon,
  title,
  description,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="group flex flex-col p-5 rounded-lg border border-fd-border/60 hover:border-fd-primary/30 bg-fd-card/80 backdrop-blur-md transition-all"
    >
      <div className="text-fd-primary mb-3">{icon}</div>
      <h3 className="font-semibold text-fd-foreground mb-1 group-hover:text-fd-primary transition-colors">
        {title}
      </h3>
      <p className="text-sm text-fd-muted-foreground">{description}</p>
    </Link>
  );
}

export function HeroContent() {
  return (
    <div className="container mx-auto px-6 pt-4 md:pt-4">
      <div className="flex flex-col items-center text-center">
        {/* Translucent text card */}
        <div className="rounded-2xl border border-fd-primary/12 bg-fd-background/30 backdrop-blur-sm shadow-[0_0_40px_-12px_rgba(77,128,255,0.1)] px-8 py-6 md:px-14 md:py-8 max-w-3xl w-full mb-16 -translate-y-10">
          {/* Badges */}
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-fd-primary/10 text-fd-primary border border-fd-primary/20">
              <Zap className="w-3.5 h-3.5" />
              Event-Sourced
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
              <Workflow className="w-3.5 h-3.5" />
              Workflow Engine
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-fd-primary/10 text-fd-primary/80 border border-fd-primary/20">
              <Eye className="w-3.5 h-3.5" />
              Full Observability
            </span>
          </div>

          {/* Main Title */}
          <h1 className="text-4xl md:text-6xl font-bold mb-2 text-fd-primary tracking-wider pb-1" style={{ fontFamily: 'var(--font-orbitron), sans-serif' }}>
            Syntropic137
          </h1>
          <p className="text-lg md:text-xl text-fd-muted-foreground mb-1">
            The Agentic Engineering Platform
          </p>
          <p className="text-base font-medium text-fd-primary/80 mb-3">
            Get out of the loop. Get into orchestration.
          </p>
          <p className="text-base text-fd-muted-foreground/70 max-w-2xl mx-auto">
            Self-hosted platform for orchestrating AI agents with event-sourced
            workflows. Every tool call, token, cost, and artifact is captured.
            Data compounds with every run.
          </p>
        </div>

        {/* Single primary CTA — floating free over the scene */}
        <Link
          href="/docs/guide/getting-started"
          className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg font-semibold text-zinc-950 bg-fd-primary hover:bg-fd-primary/80 shadow-lg shadow-fd-primary/20 hover:shadow-fd-primary/30 transition-all"
        >
          <Rocket className="w-5 h-5" />
          Get Started
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
}

export function QuickLinksGrid() {
  return (
    <section className="py-0">
      <div className="container mx-auto px-6">
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4 max-w-5xl mx-auto">
          <QuickLink
            href="/docs"
            icon={<BookOpen className="w-6 h-6" />}
            title="Documentation"
            description="Guides, concepts, and configuration"
          />
          <QuickLink
            href="/docs/cli"
            icon={<Terminal className="w-6 h-6" />}
            title="CLI Reference"
            description="Complete command documentation"
          />
          <QuickLink
            href="/docs/api"
            icon={<GitBranch className="w-6 h-6" />}
            title="API Reference"
            description="REST API with 45+ endpoints"
          />
          <QuickLink
            href="/llms"
            icon={<Bot className="w-6 h-6" />}
            title="LLM Docs"
            description="Machine-readable docs for AI agents"
          />
        </div>
      </div>
    </section>
  );
}

export function SocialFooter() {
  return (
    <section className="py-10 border-t border-fd-border">
      <div className="container mx-auto px-6 flex flex-col items-center gap-4">
        <div className="flex items-center gap-6">
          <a
            href="https://github.com/syntropic137/syntropic137"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-fd-muted-foreground hover:text-fd-primary transition-colors"
          >
            <Github className="w-5 h-5" />
            GitHub
          </a>
          <a
            href="https://x.com/syntropic137"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-fd-muted-foreground hover:text-fd-primary transition-colors"
          >
            <Twitter className="w-5 h-5" />
            Twitter
          </a>
        </div>
      </div>
    </section>
  );
}
