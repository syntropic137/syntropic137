/** Bounded-context → color mapping for the topology graph. */
export const CONTEXT_COLORS: Record<string, string> = {
  orchestration: '#4D80FF',
  workflow: '#4D80FF',
  workspace: '#4D80FF',
  session: '#1A80B3',
  observability: '#1A80B3',
  github: '#8C50DC',
  artifact: '#22cc88',
  'agentic-primitives': '#ff8844',
  'event-sourcing-platform': '#44aaff',
  cost: '#ffcc44',
  token: '#ffcc44',
};

const DEFAULT_COLOR = '#555';

/** Derive a bounded-context color from a module ID. */
export function getContextColor(moduleId: string): string {
  const lower = moduleId.toLowerCase();
  for (const [keyword, color] of Object.entries(CONTEXT_COLORS)) {
    if (lower.includes(keyword)) return color;
  }
  return DEFAULT_COLOR;
}
