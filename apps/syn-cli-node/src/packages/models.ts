import { z } from "zod";

export const PackageFormat = {
  SINGLE_WORKFLOW: "single",
  MULTI_WORKFLOW: "multi",
  STANDALONE_YAML: "standalone",
} as const;
export type PackageFormat = (typeof PackageFormat)[keyof typeof PackageFormat];

export const PluginManifestSchema = z.object({
  manifest_version: z.number().default(1),
  name: z.string().min(1),
  version: z.string().default("0.1.0"),
  description: z.string().nullish(),
  author: z.string().nullish(),
  license: z.string().nullish(),
  repository: z.string().nullish(),
}).passthrough();

export type PluginManifest = z.infer<typeof PluginManifestSchema>;

export const InstalledWorkflowRefSchema = z.object({
  id: z.string(),
  name: z.string(),
}).strict();

export type InstalledWorkflowRef = z.infer<typeof InstalledWorkflowRefSchema>;

export const InstallationRecordSchema = z.object({
  package_name: z.string(),
  package_version: z.string(),
  source: z.string(),
  source_ref: z.string(),
  installed_at: z.string(),
  format: z.string(),
  workflows: z.array(InstalledWorkflowRefSchema).default([]),
  marketplace_source: z.string().nullish(),
  git_sha: z.string().nullish(),
}).strict();

export type InstallationRecord = z.infer<typeof InstallationRecordSchema>;

export const InstalledRegistrySchema = z.object({
  version: z.number().default(1),
  installations: z.array(InstallationRecordSchema).default([]),
}).strict();

export type InstalledRegistry = z.infer<typeof InstalledRegistrySchema>;

export interface ResolvedWorkflow {
  id: string;
  name: string;
  workflow_type: string;
  classification: string;
  repository_url: string;
  repository_ref: string;
  description: string | null;
  project_name: string | null;
  phases: Record<string, unknown>[];
  requires_repos: boolean;
  input_declarations: Record<string, unknown>[];
  source_path: string;
}
