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
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                <Zap className="w-3.5 h-3.5" />
                Event-Sourced
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30">
                <Workflow className="w-3.5 h-3.5" />
                Workflow Engine
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-pink-500/20 text-pink-400 border border-pink-500/30">
                <Eye className="w-3.5 h-3.5" />
                Full Observability
              </span>
            </div>

            {/* Main Title */}
            <h1 className="text-4xl md:text-6xl font-bold mb-6 bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent pb-1">
              Agentic Engineering Framework
            </h1>
            <p className="text-lg md:text-xl text-fd-muted-foreground max-w-2xl mb-8">
              Orchestrate AI agents with event-sourced workflows. Build, observe,
              and scale agentic systems with confidence.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-wrap justify-center gap-4 mb-12">
              <Link
                href="/docs/guide/getting-started"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-semibold text-white bg-gradient-to-r from-violet-500 to-purple-500 hover:from-violet-600 hover:to-purple-600 shadow-lg shadow-purple-500/30 hover:shadow-purple-500/50 transition-all"
              >
                <Rocket className="w-5 h-5" />
                Get Started
                <ArrowRight className="w-4 h-4" />
              </Link>
              <Link
                href="/docs"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-medium border-2 border-fd-foreground/20 hover:border-fd-foreground/40 text-fd-foreground hover:bg-fd-foreground/5 transition-all"
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
            Why AEF?
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            <FeatureCard
              icon={<Workflow className="w-6 h-6" />}
              title="Workflow Engine"
              description="YAML-driven workflows with GitHub-triggered execution and human-in-the-loop controls"
              gradient="indigo"
            />
            <FeatureCard
              icon={<Activity className="w-6 h-6" />}
              title="Event Sourcing"
              description="Complete audit trail with immutable event log, replay, and temporal queries"
              gradient="purple"
            />
            <FeatureCard
              icon={<Eye className="w-6 h-6" />}
              title="Full Observability"
              description="Real-time WebSocket dashboard with token metrics, cost tracking, and tool timelines"
              gradient="pink"
            />
            <FeatureCard
              icon={<Shield className="w-6 h-6" />}
              title="Workspace Isolation"
              description="Each agent session runs in an isolated workspace with resource limits and guardrails"
              gradient="cyan"
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
              description="Set up AEF and run your first workflow"
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
  gradient,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  gradient: 'indigo' | 'purple' | 'pink' | 'cyan';
}) {
  const gradients = {
    indigo: 'from-indigo-500/10 to-indigo-500/5 border-indigo-500/20 hover:border-indigo-500/40',
    purple: 'from-purple-500/10 to-purple-500/5 border-purple-500/20 hover:border-purple-500/40',
    pink: 'from-pink-500/10 to-pink-500/5 border-pink-500/20 hover:border-pink-500/40',
    cyan: 'from-cyan-500/10 to-cyan-500/5 border-cyan-500/20 hover:border-cyan-500/40',
  };

  const iconBg = {
    indigo: 'bg-indigo-500/20 text-indigo-400',
    purple: 'bg-purple-500/20 text-purple-400',
    pink: 'bg-pink-500/20 text-pink-400',
    cyan: 'bg-cyan-500/20 text-cyan-400',
  };

  return (
    <div
      className={`group rounded-xl border bg-gradient-to-br p-6 transition-all hover:scale-[1.02] ${gradients[gradient]}`}
    >
      <div className={`inline-flex p-3 rounded-lg mb-4 ${iconBg[gradient]}`}>
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
      className="group flex flex-col p-6 rounded-xl border border-fd-border hover:border-purple-500/40 bg-fd-card hover:bg-gradient-to-br hover:from-purple-500/5 hover:to-transparent transition-all"
    >
      <div className="text-purple-400 mb-3">{icon}</div>
      <h3 className="font-semibold text-fd-foreground mb-1 group-hover:text-purple-400 transition-colors">
        {title}
      </h3>
      <p className="text-sm text-fd-muted-foreground">{description}</p>
    </Link>
  );
}
