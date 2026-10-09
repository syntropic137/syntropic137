import { Database, Activity, GitCommit, MessageCircle } from "lucide-react";
import FadeIn from "./FadeIn";

const channels = [
  {
    icon: Database,
    title: "Event-Sourced Domain Events",
    iconColor: "var(--sky-color-series-3)",
    desc: "Immutable log of every domain state change: workflows, artifacts, organizations. What was kicked off, what completed, and what failed.",
  },
  {
    icon: Activity,
    title: "Observability Events",
    iconColor: "var(--sky-color-data-3)",
    desc: <>Token usage, tool traces, and errors captured in real-time from the agent stream and <strong>git hooks</strong>. See exactly what the agent did and why. Claude Code phases add hook-level and subagent detail on top.</>,
  },
  {
    icon: MessageCircle,
    title: "Conversation Logs",
    iconColor: "var(--sky-color-accent-soft-fg)",
    desc: "Every conversation is automatically persisted to S3-compatible storage. Never lose track of agent reasoning, decisions, or context. Review any session from any workflow, anytime.",
  },
  {
    icon: GitCommit,
    title: "Git Hooks",
    iconColor: "var(--sky-color-series-4)",
    desc: "Every commit, push, branch, and merge captured as events. Correlate code changes with the agent sessions that produced them.",
  },
];

export default function Observability() {
  return (
    <section id="observability" className="section section-alt">
      <div className="container">
        <h2 className="section-heading">
          Immutable <span className="accent">Event Store</span>
        </h2>
        <p className="section-subtitle">
          Multiple observability channels. All data is interactive, all data compounds.
        </p>
        <div className="cards-grid cards-grid--two">
          {channels.map((channel) => (
            <FadeIn key={channel.title}>
              <div
                className="card glass card-horizontal"
                style={{
                  "--icon-color": channel.iconColor,
                } as React.CSSProperties}
              >
                <div className="card-icon-chip">
                  <channel.icon size={22} strokeWidth={1.5} />
                </div>
                <div>
                  <h3 className="card-title">{channel.title}</h3>
                  <p className="card-desc">{channel.desc}</p>
                </div>
              </div>
            </FadeIn>
          ))}
        </div>
        <FadeIn>
          <p className="how-it-works-caption">
            Analyze what agents do across sessions, workflows, repos, systems, and organizations. Data compounds. Every run makes the next one smarter.
          </p>
        </FadeIn>
      </div>
    </section>
  );
}
