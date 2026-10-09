import { RefreshCw, Database, GitPullRequest } from "lucide-react";
import FadeIn from "./FadeIn";

const cards = [
  {
    icon: RefreshCw,
    title: "Repeatable Workflows",
    href: "#how-it-works",
    num: "01",
    accent: "#4D80FF", // signature blue
    desc: <>Multi-phase pipelines defined as commands. Research, plan, implement, review. Every phase picks its own harness, Claude Code or Codex, and every workflow runs the same way, every time.</>,
  },
  {
    icon: Database,
    title: "Immutable Event Store",
    href: "#observability",
    num: "02",
    accent: "#60a5fa",
    desc: <>Every state change is a permanent, queryable event. Domain events, observability telemetry, and conversation logs. Nothing is ever lost. Data compounds with every run.</>,
  },
  {
    icon: GitPullRequest,
    title: "GitHub-Native Triggers",
    href: "#triggers",
    num: "03",
    accent: "#818cf8",
    desc: <>Webhook triggers enable self-healing CI, auto-responses to review comments, and PR-driven workflows. Agents respond in minutes. Developers stay out of the loop.</>,
  },
];

export default function WhySyntropic() {
  return (
    <section id="features" className="section section-alt">
      <div className="container">
        <h2 className="section-heading">
          Why <span className="accent">Syntropic137?</span>
        </h2>
        <p className="section-subtitle">Built for production. Built to last.</p>
        <div className="cards-grid">
          {cards.map((card) => (
            <FadeIn key={card.title}>
              <a
                href={card.href}
                className="card glass card-link card-accented"
                style={{ "--card-accent": card.accent } as React.CSSProperties}
              >
                <span className="card-num">{card.num}</span>
                <card.icon className="card-icon" size={40} strokeWidth={1.5} />
                <h3 className="card-title">{card.title}</h3>
                <p className="card-desc">{card.desc}</p>
              </a>
            </FadeIn>
          ))}
        </div>
      </div>
    </section>
  );
}
