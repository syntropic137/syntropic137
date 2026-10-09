import { Search, FileText, Code2, MessageSquareText, ArrowRight } from "lucide-react";
import FadeIn from "./FadeIn";

const phases = [
  { icon: Search,            title: "Research",   subtitle: "/research $ARGUMENTS",  stepNum: "01", stepColor: "#4D80FF" },
  { icon: FileText,          title: "Plan",        subtitle: "/plan $ARGUMENTS",       stepNum: "02", stepColor: "#a78bfa" },
  { icon: Code2,             title: "Implement",   subtitle: "/implement $ARGUMENTS",  stepNum: "03", stepColor: "#34d399" },
  { icon: MessageSquareText, title: "Review",      subtitle: "/review $ARGUMENTS",     stepNum: "04", stepColor: "#f59e0b" },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="section section-alt">
      <div className="container">
        <h2 className="section-heading">
          Workflow Phases as{" "}
          <span className="accent">Commands</span>
        </h2>
        <p className="section-subtitle">
          Prompt-and-command conventions you already know, running on <strong>Claude Code</strong> or <strong>Codex</strong>. Scale to <span className="text-green">100+ agents with Syntropic137</span>, <em>versus &lt;10 human-in-the-loop agentic IDEs.</em>
        </p>
        <FadeIn>
          <div className="arch-flow">
            {phases.map((phase, i) => (
              <div key={phase.title} className="arch-step">
                <div
                  className="arch-node glass arch-node-accented"
                  style={{ "--step-color": phase.stepColor } as React.CSSProperties}
                >
                  <div className="arch-step-num">{phase.stepNum}</div>
                  <phase.icon className="arch-icon" size={32} strokeWidth={1.5} />
                  <div className="arch-title">{phase.title}</div>
                  <div className="arch-subtitle">
                    <code className="phase-cmd">{phase.subtitle}</code>
                  </div>
                </div>
                {i < phases.length - 1 && (
                  <div className="arch-arrow">
                    <ArrowRight size={24} strokeWidth={2} />
                  </div>
                )}
              </div>
            ))}
          </div>
          <p className="how-it-works-caption">
            Each phase runs in an isolated Docker workspace. Output artifacts flow forward: research informs the plan, the plan drives implementation, implementation feeds review. The same workflow that runs once runs a thousand times.
          </p>
        </FadeIn>
      </div>
    </section>
  );
}
