import { Shield, Server, Globe } from "lucide-react";
import FadeIn from "./FadeIn";

const cards = [
  {
    icon: Shield,
    title: "Isolated by Default",
    iconColor: "#34d399",
    iconBg: "rgba(52, 211, 153, 0.08)",
    iconBgHover: "rgba(52, 211, 153, 0.16)",
    iconGlow: "rgba(52, 211, 153, 0.28)",
    desc: "Every agent runs in an ephemeral Docker container. Harness credentials are provider-scoped, and setup tokens are cleared before the agent starts. Outbound traffic routes through an Envoy sidecar. Read-only filesystems. No new privileges. Supply chain signed with cosign.",
  },
  {
    icon: Server,
    title: "Built to Recover",
    iconColor: "#10b981",
    iconBg: "rgba(16, 185, 129, 0.08)",
    iconBgHover: "rgba(16, 185, 129, 0.16)",
    iconGlow: "rgba(16, 185, 129, 0.28)",
    desc: "Event-sourced state survives crashes. Idempotent handlers replay safely. Single-machine Docker Compose deployment. No Kubernetes required.",
  },
  {
    icon: Globe,
    title: "Accessible from Anywhere",
    iconColor: "#6ee7b7",
    iconBg: "rgba(110, 231, 183, 0.08)",
    iconBgHover: "rgba(110, 231, 183, 0.16)",
    iconGlow: "rgba(110, 231, 183, 0.28)",
    desc: "Built-in Cloudflare Tunnel support. Receive GitHub webhooks and access your system from anywhere without exposing ports or managing DNS.",
  },
];

export default function Security() {
  return (
    <section id="security" className="section">
      <div className="container">
        <h2 className="section-heading">
          Production <span className="accent">Ready</span>
        </h2>
        <p className="section-subtitle">
          Security as a first-class citizen
        </p>
        <div className="cards-grid">
          {cards.map((card) => (
            <FadeIn key={card.title}>
              <div
                className="card glass card-security"
                style={{
                  "--icon-color": card.iconColor,
                  "--icon-bg": card.iconBg,
                  "--icon-bg-hover": card.iconBgHover,
                  "--icon-glow": card.iconGlow,
                } as React.CSSProperties}
              >
                <div className="security-icon-ring">
                  <card.icon size={28} strokeWidth={1.5} />
                </div>
                <h3 className="card-title">{card.title}</h3>
                <p className="card-desc">{card.desc}</p>
              </div>
            </FadeIn>
          ))}
        </div>
      </div>
    </section>
  );
}
