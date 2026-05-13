import { z } from "zod";

export const SyntropicMarkerSchema = z.object({
  type: z.string(),
  min_platform_version: z.string().default("0.0.0"),
}).passthrough();

export type SyntropicMarker = z.infer<typeof SyntropicMarkerSchema>;

export const MarketplacePluginEntrySchema = z.object({
  name: z.string().min(1),
  source: z.string(),
  version: z.string().default("0.1.0"),
  description: z.string().default(""),
  category: z.string().default(""),
  tags: z.array(z.string()).default([]),
  // WHY (#763): claude-plugin marketplaces use `ref` per-plugin to pin
  // versions independently of the marketplace repo's default branch. We
  // accept it as optional metadata; the resolver falls back to the parent
  // entry.ref when missing.
  ref: z.string().optional(),
}).passthrough();

export type MarketplacePluginEntry = z.infer<typeof MarketplacePluginEntrySchema>;

export const MarketplaceIndexSchema = z.object({
  name: z.string().min(1),
  // WHY (#763): the syntropic137 marker is optional so we can ingest plain
  // claude-plugin marketplaces (e.g. AgentParadise/agentic-primitives) that
  // do not advertise themselves as workflow marketplaces. Workflow code
  // still asserts `syntropic137.type === 'workflow-marketplace'` separately.
  syntropic137: SyntropicMarkerSchema.optional(),
  plugins: z.array(MarketplacePluginEntrySchema).default([]),
}).passthrough();

export type MarketplaceIndex = z.infer<typeof MarketplaceIndexSchema>;

export const RegistryEntrySchema = z.object({
  repo: z.string(),
  ref: z.string().default("main"),
  added_at: z.string(),
}).strict();

export type RegistryEntry = z.infer<typeof RegistryEntrySchema>;

export const RegistryConfigSchema = z.object({
  version: z.number().default(1),
  registries: z.record(z.string(), RegistryEntrySchema).default({}),
}).strict();

export type RegistryConfig = z.infer<typeof RegistryConfigSchema>;

export const CachedMarketplaceSchema = z.object({
  fetched_at: z.string(),
  index: MarketplaceIndexSchema,
}).strict();

export type CachedMarketplace = z.infer<typeof CachedMarketplaceSchema>;
