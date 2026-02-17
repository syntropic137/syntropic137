'use client';

import Link from 'next/link';
import { ArrowRight, BookOpen, Rocket, Terminal, Activity, Workflow, Eye, Shield, Zap, GitBranch, Bot } from 'lucide-react';
import { HeroScene } from '@/components/HeroScene';

export default function HomePage() {
  return (
    <main className="flex-1">
      {/* Hero Section */}
      <section className="relative overflow-hidden">
        <div className="container mx-auto px-6 py-16 md:py-24">
          <div className="flex flex-col items-center text-center">
            {/* Badges */}
            <div className="flex flex-wrap justify-center gap-2 mb-6">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-sky-500/10 text-sky-400 border border-sky-500/20">
                <Zap className="w-3.5 h-3.5" />
                Event-Sourced
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
                <Workflow className="w-3.5 h-3.5" />
                Workflow Engine
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-sky-500/10 text-sky-300 border border-sky-500/20">
                <Eye className="w-3.5 h-3.5" />
                Full Observability
              </span>
            </div>

            {/* Main Title */}
            <h1 className="text-4xl md:text-6xl font-bold mb-2 text-fd-foreground tracking-tight pb-1">
              Syntropic<span className="text-sky-400">137</span>
            </h1>
            <p className="text-lg md:text-xl text-fd-muted-foreground mb-1">
              Agentic Engineering Framework
            </p>
            <p className="text-base text-fd-muted-foreground/70 max-w-2xl mb-8">
              Orchestrate AI agents with event-sourced workflows. Build, observe,
              and scale agentic systems with precision.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-wrap justify-center gap-4 mb-12">
              <Link
                href="/docs/guide/getting-started"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-zinc-950 bg-sky-400 hover:bg-sky-300 shadow-lg shadow-sky-500/20 hover:shadow-sky-500/30 transition-all"
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
            </div>

            {/* Three.js Scene */}
            <div className="w-full max-w-4xl">
              <HeroScene />
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-16 border-t border-fd-border">
        <div className="container mx-auto px-6">
          <h2 className="text-2xl md:text-3xl font-bold text-center mb-12">
            Why Syntropic137?
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <FeatureCard
              icon={<Workflow className="w-6 h-6" />}
              title="Workflow Engine"
              description="YAML-driven workflows with GitHub-triggered execution and human-in-the-loop controls"
              variant="primary"
            />
            <FeatureCard
              icon={<Activity className="w-6 h-6" />}
              title="Event Sourcing"
              description="Complete audit trail with immutable event log, replay, and temporal queries"
              variant="secondary"
            />
            <FeatureCard
              icon={<Eye className="w-6 h-6" />}
              title="Full Observability"
              description="Real-time WebSocket dashboard with token metrics, cost tracking, and tool timelines"
              variant="primary"
            />
            <FeatureCard
              icon={<Shield className="w-6 h-6" />}
              title="Workspace Isolation"
              description="Each agent session runs in an isolated workspace with resource limits and guardrails"
              variant="secondary"
            />
          </div>
        </div>
      </section>

      {/* Quick Links */}
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
              href="/llms.txt"
              icon={<Bot className="w-6 h-6" />}
              title="LLM Docs"
              description="Machine-readable docs for AI agents"
            />
          </div>
        </div>
      </section>
    </main>
  );
}

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
    primary: 'from-sky-500/8 to-sky-500/3 border-sky-500/15 hover:border-sky-500/30',
    secondary: 'from-zinc-500/8 to-zinc-500/3 border-zinc-500/15 hover:border-zinc-500/30',
  };
  const iconStyles = {
    primary: 'bg-sky-500/15 text-sky-400',
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
      className="group flex flex-col p-6 rounded-lg border border-fd-border hover:border-sky-500/30 bg-fd-card transition-all"
    >
      <div className="text-sky-400 mb-3">{icon}</div>
      <h3 className="font-semibold text-fd-foreground mb-1 group-hover:text-sky-400 transition-colors">
        {title}
      </h3>
      <p className="text-sm text-fd-muted-foreground">{description}</p>
    </Link>
  );
}
