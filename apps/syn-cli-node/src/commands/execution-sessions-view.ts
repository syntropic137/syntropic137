/**
 * Human rendering of a revision-pinned session inventory (#1398 D).
 *
 * Pure: pages in, lines out. Counts, coverage and completeness text come from
 * the API summary verbatim; this module only joins sections by the qualified
 * node keys the API returns (`item_keys`), never by re-deriving identity.
 */
import type { components } from "../generated/api-types.js";

type Page = components["schemas"]["SessionInventoryPageResponse"];
type Item = Page["items"][number];
type Ref = components["schemas"]["InventoryNodeRef"];
type Node = Extract<Item, { ref: unknown }>;
type Membership = Extract<Item, { run: unknown }>;
type Edge = Extract<Item, { parent: unknown }>;
type Capture = Extract<Item, { availability: unknown }>;
type Gap = Extract<Item, { reason: unknown }>;
type Binding = Extract<Item, { owner: unknown }>;
type Retraction = Extract<Item, { target: unknown }>;
type Kind = Page["kind"];
type Keys = Page["item_keys"][number] | undefined;
type Remote = "enabled" | "disabled";

/** `transcript:claude`, `platform`, `invocation`: the namespace a local id lives in. */
export function namespaceOf(ref: Ref): string {
  return ref.harness == null ? ref.kind : `${ref.kind}:${ref.harness}`;
}

function qualified(ref: Ref): string {
  return `${namespaceOf(ref)}/${ref.local_id}`;
}

interface Joined {
  nodes: Map<string, Node>;
  memberships: Map<string, Membership[]>;
  parents: Map<string, Edge[]>;
  captures: Map<string, Capture[]>;
  owners: Map<string, Binding[]>;
  gaps: Gap[];
  overrides: NonNullable<Page["body_overrides"]>;
}

function push<T>(map: Map<string, T[]>, key: string | null | undefined, value: T): void {
  if (!key) return;
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

// Each section's item type is fixed by the page kind, so dispatch on the kind.
const collectors: Record<Kind, (joined: Joined, item: Item, keys: Keys) => void> = {
  node: (joined, item, keys) => { if (keys?.node_key) joined.nodes.set(keys.node_key, item as Node); },
  membership: (joined, item, keys) => push(joined.memberships, keys?.node_key, item as Membership),
  edge: (joined, item, keys) => push(joined.parents, keys?.peer_key, item as Edge),
  capture: (joined, item, keys) => push(joined.captures, keys?.node_key, item as Capture),
  binding: (joined, item, keys) => push(joined.owners, keys?.peer_key, item as Binding),
  gap: (joined, item) => { joined.gaps.push(item as Gap); },
  retraction: () => undefined,
};

function join(pages: readonly Page[]): Joined {
  const joined: Joined = {
    nodes: new Map(), memberships: new Map(), parents: new Map(), captures: new Map(),
    owners: new Map(), gaps: [], overrides: [],
  };
  for (const page of pages) {
    joined.overrides.push(...(page.body_overrides ?? []));
    const collect = collectors[page.kind];
    page.items.forEach((item, index) => collect(joined, item, page.item_keys[index]));
  }
  return joined;
}

function localAvailability(captures: readonly Capture[], overrides: Joined["overrides"]): string {
  const local = captures.filter(capture => (capture.destination ?? "local") === "local");
  if (local.length === 0) return "not captured";
  return local.map(capture => {
    const current = overrides.find(state => state.archive_sha256 === capture.archived_byte_hash)?.status;
    return current ? `${capture.availability} (now ${current})` : capture.availability;
  }).join(", ");
}

function replication(captures: readonly Capture[], remote: Remote): string {
  const replicated = captures.filter(capture => capture.destination === "remote");
  if (replicated.length > 0) return replicated.map(capture => capture.availability).join(", ");
  return remote === "disabled" ? "remote replication disabled" : "not replicated";
}

function nodeLines(key: string, joined: Joined, remote: Remote): string[] {
  const node = joined.nodes.get(key)!;
  const lines = [`  ${qualified(node.ref)}`];
  lines.push(`    harness: ${node.ref.harness ?? "-"}; kind: ${node.ref.kind}; source: ${node.ref.source_instance_id}`);
  for (const edge of joined.parents.get(key) ?? []) {
    lines.push(`    parent: ${qualified(edge.parent)} (${edge.relation}, ${edge.confidence})`);
  }
  for (const binding of joined.owners.get(key) ?? []) {
    lines.push(`    represents: ${qualified(binding.owner)} (${binding.confidence})`);
  }
  const captures = joined.captures.get(key) ?? [];
  if (node.ref.kind === "transcript" || captures.length > 0) {
    lines.push(`    local: ${localAvailability(captures, joined.overrides)}; replication: ${replication(captures, remote)}`);
  }
  return lines;
}

function groupLabel(membership: Membership): string {
  return `Phase ${membership.phase_id ?? "(unassigned)"} / attempt ${membership.attempt_id ?? "(unknown)"}`;
}

function groupByPhase(joined: Joined): Map<string, Set<string>> {
  const groups = new Map<string, Set<string>>();
  for (const [key, memberships] of joined.memberships) {
    for (const membership of memberships) {
      const label = groupLabel(membership);
      const group = groups.get(label) ?? new Set<string>();
      group.add(key);
      groups.set(label, group);
    }
  }
  return groups;
}

function renderGroups(joined: Joined, remote: Remote): string[] {
  const groups = groupByPhase(joined);
  const lines: string[] = [];
  for (const label of [...groups.keys()].sort()) {
    lines.push("", label);
    const present = [...groups.get(label)!].filter(key => joined.nodes.has(key));
    for (const key of present) lines.push(...nodeLines(key, joined, remote));
  }
  return lines;
}

function renderUnlinked(joined: Joined, remote: Remote): string[] {
  const unlinked = [...joined.nodes.keys()].filter(key => !joined.memberships.has(key));
  if (unlinked.length === 0) return [];
  return ["", "Unlinked (no phase membership)", ...unlinked.flatMap(key => nodeLines(key, joined, remote))];
}

function gapLine(gap: Gap, joined: Joined): string {
  const affected = (gap.node_keys ?? []).map(key => {
    const node = joined.nodes.get(key);
    return node ? qualified(node.ref) : key;
  });
  return `  ${gap.reason}${affected.length > 0 ? `: ${affected.join(", ")}` : " (run-level)"}`;
}

function renderGaps(joined: Joined): string[] {
  if (joined.gaps.length === 0) return [];
  return ["", "Gaps", ...joined.gaps.map(gap => gapLine(gap, joined))];
}

/** Full inventory view: grouped by phase/attempt, then unlinked sessions, then gaps. */
export function renderInventory(pages: readonly Page[], remote: Remote): string[] {
  const joined = join(pages);
  return [...renderGroups(joined, remote), ...renderUnlinked(joined, remote), ...renderGaps(joined)];
}

function captureLines(item: Capture, page: Page, remote: Remote): string[] {
  const local = (item.destination ?? "local") === "local";
  const current = local ? page.body_overrides?.find(state => state.archive_sha256 === item.archived_byte_hash)?.status : undefined;
  const where = local ? "local" : `remote (replication ${remote})`;
  const lines = [`${qualified(item.node)}\t${where}: recorded=${item.availability}; current=${current ?? "unchecked"}`];
  if (item.archived_byte_hash) lines.push(`Archive: ${item.archived_byte_hash}`);
  return lines;
}

const itemRenderers: Record<Kind, (item: Item, page: Page, remote: Remote) => string[]> = {
  node: item => [`${namespaceOf((item as Node).ref)}\t${(item as Node).ref.local_id}`],
  membership: item => {
    const m = item as Membership;
    return [`${qualified(m.node)}\tphase=${m.phase_id ?? "-"}\tattempt=${m.attempt_id ?? "-"}\t${m.confidence}`];
  },
  edge: item => {
    const e = item as Edge;
    return [`${qualified(e.parent)} -> ${qualified(e.child)}\t${e.relation}\t${e.confidence}`];
  },
  capture: (item, page, remote) => captureLines(item as Capture, page, remote),
  binding: item => {
    const b = item as Binding;
    return [`${qualified(b.owner)} represents ${qualified(b.transcript)}\t${b.confidence}`];
  },
  gap: item => {
    const g = item as Gap;
    return [`${g.reason}\taffected=${(g.node_keys ?? []).length}\tevidence=${(g.evidence_ids ?? []).length}`];
  },
  retraction: item => {
    const r = item as Retraction;
    return [`correction: ${r.target.evidence_id} corrected by ${r.evidence.evidence_id}`];
  },
};

/** One section page, for single-section browsing. Always full IDs. */
export function renderItems(page: Page, remote: Remote): string[] {
  const render = itemRenderers[page.kind];
  return page.items.flatMap(item => render(item, page, remote));
}
