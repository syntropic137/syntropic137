'use client';

import Link from 'next/link';
import { ArrowRight, BookOpen, Rocket, Terminal, Activity, Workflow, Eye, Shield, Zap, GitBranch, Bot, Github, Twitter } from 'lucide-react';
import { HeroScene } from '@/components/HeroScene';

function FeatureCard({
  icon,
  title,
  description,
  variant,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  variant: 'primary' | 'secondary';
}) {
  const styles = {
    primary: 'from-fd-primary/8 to-fd-primary/3 border-fd-primary/15 hover:border-fd-primary/30',
    secondary: 'from-zinc-500/8 to-zinc-500/3 border-zinc-500/15 hover:border-zinc-500/30',
  };
  const iconStyles = {
    primary: 'bg-fd-primary/15 text-fd-primary',
    secondary: 'bg-zinc-500/15 text-zinc-400',
  };

  return (
    <div
      className={`group rounded-lg border bg-gradient-to-br p-6 transition-all ${styles[variant]}`}
    >
      <div className={`inline-flex p-3 rounded-lg mb-4 ${iconStyles[variant]}`}>
        {icon}
      </div>
      <h3 className="font-semibold text-fd-foreground mb-2">{title}</h3>
      <p className="text-sm text-fd-muted-foreground">{description}</p>
    </div>
  );
}

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
      className="group flex flex-col p-6 rounded-lg border border-fd-border hover:border-fd-primary/30 bg-fd-card transition-all"
    >
      <div className="text-fd-primary mb-3">{icon}</div>
      <h3 className="font-semibold text-fd-foreground mb-1 group-hover:text-fd-primary transition-colors">
        {title}
      </h3>
      <p className="text-sm text-fd-muted-foreground">{description}</p>
    </Link>
  );
}

export function HeroSection() {
  return (
    <section className="relative overflow-hidden">
      <div className="container mx-auto px-6 py-16 md:py-24">
        <div className="flex flex-col items-center text-center">
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
          <p className="text-base text-fd-muted-foreground/70 max-w-2xl mb-8">
            Self-hosted platform for orchestrating AI agents with event-sourced
            workflows. Every tool call, token, cost, and artifact is captured
            — data compounds with every run.
          </p>

          {/* CTA Buttons */}
          <div className="flex flex-wrap justify-center gap-4 mb-12">
            <Link
              href="/docs/guide/getting-started"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-zinc-950 bg-fd-primary hover:bg-fd-primary/80 shadow-lg shadow-fd-primary/20 hover:shadow-fd-primary/30 transition-all"
            >
              <Rocket className="w-5 h-5" />
              Get Started
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link
              href="/docs"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium border border-zinc-700 hover:border-zinc-500 text-fd-foreground hover:bg-zinc-800/50 transition-all"
            >
              <BookOpen className="w-5 h-5" />
              Documentation
            </Link>
            <Link
              href="/llms"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium border border-zinc-700 hover:border-zinc-500 text-fd-foreground hover:bg-zinc-800/50 transition-all"
            >
              <Bot className="w-5 h-5" />
              LLM Docs
            </Link>
          </div>

          {/* Three.js Scene */}
          <div className="w-full max-w-4xl">
            <HeroScene />
          </div>
        </div>
      </div>
    </section>
  );
}

export function FeaturesGrid() {
  return (
    <section className="py-16 border-t border-fd-border">
      <div className="container mx-auto px-6">
        <h2 className="text-2xl md:text-3xl font-bold text-center mb-12">
          Why Syntropic137?
        </h2>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
          <FeatureCard
            icon={<Workflow className="w-6 h-6" />}
            title="Repeatable Workflows"
            description="Multi-phase pipelines built on the Claude Code command standard. Research, plan, implement, review — every workflow runs the same way, every time."
            variant="primary"
          />
          <FeatureCard
            icon={<Activity className="w-6 h-6" />}
            title="Immutable Event Store"
            description="Every state change is a permanent, queryable event. Domain events, observability telemetry, and conversation logs — nothing is ever lost."
            variant="secondary"
          />
          <FeatureCard
            icon={<GitBranch className="w-6 h-6" />}
            title="GitHub-Native Triggers"
            description="Webhook triggers enable self-healing CI, auto-responses to review comments, and PR-driven workflows. Agents respond in minutes."
            variant="primary"
          />
          <FeatureCard
            icon={<Shield className="w-6 h-6" />}
            title="Workspace Isolation"
            description="Every agent runs in an ephemeral Docker container. API keys are never exposed to workspaces. Egress proxies control outbound traffic."
            variant="secondary"
          />
        </div>
      </div>
    </section>
  );
}

export function QuickLinksGrid() {
  return (
    <section className="py-16 border-t border-fd-border">
      <div className="container mx-auto px-6">
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-5xl mx-auto">
          <QuickLink
            href="/docs/guide/getting-started"
            icon={<Rocket className="w-6 h-6" />}
            title="Quick Start"
            description="Set up and run your first workflow"
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
