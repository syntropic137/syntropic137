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
  // WHY min(1) (issue #822): an empty version passes a truthiness check on
  // the way out, so the query param is omitted and the install silently takes
  // the unversioned overwrite path. The policy is only as good as the version
  // being present.
  version: z.string().trim().min(1, "manifest version must not be empty").default("0.1.0"),
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
  input_declarations: Record<string, unknown>[];
  source_path: string;
  /**
   * The whole workflow document, with `prompt_file:` refs already resolved.
   *
   * WHY this exists alongside the named fields above: install uploads this to
   * `/workflows/from-yaml`, where the server owns every YAML semantic. The
   * named fields are a lossy projection kept for local preview and the
   * install registry - anything the projection does not name (skills,
   * claude_plugins, and whatever is added next) survives only here.
   *
   * WHY there is no `requires_repos` among the named fields (#1050): the CLI
   * used to compute one, inferring `false` when the YAML declared no
   * `repository:`, while the server infers `true` for the same YAML. Nothing
   * read the CLI's answer, so the disagreement stayed invisible until an
   * author hit the 422 it contradicted. `requires_repos` is declared in the
   * document above and decided by the server's `infer_requires_repos`; read
   * it off an API response, never re-derive it here.
   */
  definition: Record<string, unknown>;
}
