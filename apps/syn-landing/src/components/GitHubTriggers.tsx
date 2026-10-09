import { CheckCircle2, GitPullRequest, MessageSquare } from "lucide-react";
import FadeIn from "./FadeIn";

const triggerLines = [
  { num: 1, content: <><span className="syn-punctuation">$ </span><span className="syn-function">syn triggers register</span> <span className="syn-property">--name</span> <span className="syn-string">"self-healing"</span> <span className="syn-punctuation">\</span></> },
  { num: 2, content: <><span className="syn-punctuation">    </span><span className="syn-property">--event</span> <span className="syn-string">"check_run.completed"</span> <span className="syn-punctuation">\</span></> },
  { num: 3, content: <><span className="syn-punctuation">    </span><span className="syn-property">--repository</span> <span className="syn-string">acme/api</span> <span className="syn-punctuation">\</span></> },
  { num: 4, content: <><span className="syn-punctuation">    </span><span className="syn-property">--workflow</span> <span className="syn-string">fix-and-pr</span></> },
  { num: 5, content: null },
  { num: 6, content: <span className="syn-comment"># CI fails → webhook fires → your agent opens a fix PR</span> },
  { num: 7, content: null },
  { num: 8, content: <><span className="syn-punctuation">$ </span><span className="syn-function">syn triggers register</span> <span className="syn-property">--name</span> <span className="syn-string">"pr-review"</span> <span className="syn-punctuation">\</span></> },
  { num: 9, content: <><span className="syn-punctuation">    </span><span className="syn-property">--event</span> <span className="syn-string">"pull_request.opened"</span> <span className="syn-punctuation">\</span></> },
  { num: 10, content: <><span className="syn-punctuation">    </span><span className="syn-property">--repository</span> <span className="syn-string">acme/api</span> <span className="syn-punctuation">\</span></> },
  { num: 11, content: <><span className="syn-punctuation">    </span><span className="syn-property">--workflow</span> <span className="syn-string">code-review</span></> },
  { num: 12, content: null },
  { num: 13, content: <span className="syn-comment"># PR opened → your agent reviews it in minutes</span> },
];

const triggers = [
  {
    icon: CheckCircle2,
    label: "CI Check",
    event: "check_run.completed",
    action: "Self-healing CI: auto-fix and open PR",
    color: "#34d399",
    bg: "rgba(52, 211, 153, 0.12)",
  },
  {
    icon: GitPullRequest,
    label: "Pull Request",
    event: "pull_request.opened",
    action: "Automated code review in minutes",
    color: "#4D80FF",
    bg: "rgba(77, 128, 255, 0.12)",
  },
  {
    icon: MessageSquare,
    label: "Issue Comment",
    event: "issue_comment.created",
    action: "Auto-respond to review comments",
    color: "#a78bfa",
    bg: "rgba(167, 139, 250, 0.12)",
  },
];

export default function GitHubTriggers() {
  return (
    <section id="triggers" className="section">
      <div className="container">
        <h2 className="section-heading">
          <span className="accent">GitHub-Native</span> Triggers
        </h2>
        <p className="section-subtitle">
          Webhook triggers kick off workflows automatically. Developers stay out of the loop.
        </p>
        <FadeIn>
          <div className="code-editor glass">
            <div className="code-titlebar">
              <div className="code-dots">
                <span className="dot dot-red" />
                <span className="dot dot-yellow" />
                <span className="dot dot-green" />
              </div>
              <span className="code-filename">terminal</span>
            </div>
            <div className="code-body">
              <div className="code-line-numbers" aria-hidden="true">
                {triggerLines.map((l) => (
                  <span key={l.num}>{l.num}</span>
                ))}
              </div>
              <pre style={{ margin: 0 }}><code>{triggerLines.map((l, i) => (
                <span key={l.num}>{i > 0 && "\n"}{l.content ?? ""}</span>
              ))}</code></pre>
            </div>
          </div>
          <div className="triggers-examples">
            {triggers.map((t) => (
              <div
                key={t.event}
                className="glass trigger-card-v2"
                style={{
                  "--trigger-color": t.color,
                  "--trigger-bg": t.bg,
                } as React.CSSProperties}
              >
                <div className="trigger-icon-chip">
                  <t.icon size={18} strokeWidth={1.75} />
                </div>
                <div className="trigger-event-col">
                  <span className="trigger-label">{t.label}</span>
                  <span className="trigger-event">{t.event}</span>
                </div>
                <span className="trigger-arrow">→</span>
                <span className="trigger-action">{t.action}</span>
              </div>
            ))}
          </div>
        </FadeIn>
      </div>
    </section>
  );
}
