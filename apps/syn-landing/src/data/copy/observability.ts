/**
 * "03 Fully observable" copy (#observability), from the v4 boards. The
 * isolation sentence carries the facts of the old Security section: an
 * ephemeral container per agent, setup credentials cleared before the agent
 * starts, outbound traffic through the Envoy proxy.
 */

export const OBSERVABILITY = {
  num: "03",
  eyebrow: "Fully observable",
  title: "See every step. Pay for none of the surprises.",
  lede: "Every tool call, token and dollar, per phase, live. Every agent runs in a throwaway container with credentials cleared and outbound traffic proxied.",
  points: [
    { title: "Live and permanent", body: "Watch runs as they happen; the event store keeps every decision." },
    { title: "Cost to the cent", body: "Per run, per phase, per token type, per model." },
    { title: "Readable by agents too", body: "The CLI and API return the same facts as JSON." },
  ],
  toolLogLabel: "Tool calls of the run, newest last",
} as const;
