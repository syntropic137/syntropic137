import fs from "node:fs";
import path from "node:path";
import { synPath } from "../persistence/store.js";
import { readJsonFile, writeJsonFile } from "../persistence/store.js";
import {
  type InstalledRegistry,
  InstalledRegistrySchema,
  type InstalledWorkflowRef,
  type PackageFormat,
  type PluginManifest,
  PluginManifestSchema,
  type ResolvedWorkflow,
} from "./models.js";
import { gitClone, gitHeadSha, makeTempDir, removeTempDir } from "./git.js";
import { parseYaml } from "./yaml.js";

const INSTALLED_PATH = synPath("workflows", "installed.json");

// ---------------------------------------------------------------------------
// Installed registry I/O
// ---------------------------------------------------------------------------

export function loadInstalled(): InstalledRegistry {
  const fallback: InstalledRegistry = { version: 1, installations: [] };
  return readJsonFile(INSTALLED_PATH, InstalledRegistrySchema, fallback);
}

export function saveInstalled(registry: InstalledRegistry): void {
  writeJsonFile(INSTALLED_PATH, registry);
}

export function recordInstallation(opts: {
  packageName: string;
  packageVersion: string;
  source: string;
  sourceRef: string;
  format: PackageFormat;
  workflows: InstalledWorkflowRef[];
  marketplaceSource?: string | null;
  gitSha?: string | null;
}): void {
  const registry = loadInstalled();
  const record = {
    package_name: opts.packageName,
    package_version: opts.packageVersion,
    source: opts.source,
    source_ref: opts.sourceRef,
    installed_at: new Date().toISOString(),
    format: opts.format,
    workflows: opts.workflows,
    marketplace_source: opts.marketplaceSource ?? null,
    git_sha: opts.gitSha ?? null,
  };
  // WHY dedup by package_name (issue #822): this used to append
  // unconditionally, and only `update` got away with it because it called
  // removeInstallation first. Now that install is an upsert server-side, a
  // second install of the same package would append a duplicate registry
  // entry pointing at the same workflow ids, so `list` double-counts and
  // `uninstall` removes only one of them. One installation per package.
  const filtered = registry.installations.filter(
    (i) => i.package_name !== opts.packageName,
  );
  saveInstalled({
    version: registry.version,
    installations: [...filtered, record],
  });
}

// ---------------------------------------------------------------------------
// ADR-058: requires_repos default inference
// ---------------------------------------------------------------------------

function inferRequiresRepos(data: Record<string, unknown>): boolean {
  if (data["requires_repos"] === true) return true;
  if (data["requires_repos"] === false) return false;
  return data["repository"] != null;
}

// ---------------------------------------------------------------------------
// Source parsing
// ---------------------------------------------------------------------------

const REMOTE_PREFIXES = ["https://", "http://", "git@", "ssh://"];

function isRemoteUrl(source: string): boolean {
  return REMOTE_PREFIXES.some((prefix) => source.startsWith(prefix));
}

function isLocalPath(source: string): boolean {
  return (
    fs.existsSync(source) ||
    source.startsWith(".") ||
    source.startsWith("/") ||
    source.startsWith("~")
  );
}

// GitHub shorthand is exactly `owner/repo` - two non-empty segments, nothing
// else. Anything with more segments (`foo/bar/baz`) has no such repo identity
// and must not be turned into a fabricated github.com URL.
function isGitHubShorthand(source: string): boolean {
  if (source.includes("@")) return false;
  const segments = source.split("/");
  return segments.length === 2 && segments.every((segment) => segment.length > 0);
}

export function parseSource(source: string): { resolved: string; isRemote: boolean } {
  if (isRemoteUrl(source)) {
    return { resolved: source, isRemote: true };
  }
  if (isLocalPath(source)) {
    return { resolved: source, isRemote: false };
  }
  if (isGitHubShorthand(source)) {
    return { resolved: `https://github.com/${source}.git`, isRemote: true };
  }
  return { resolved: source, isRemote: false };
}

// ---------------------------------------------------------------------------
// Package format detection
// ---------------------------------------------------------------------------

export function detectFormat(pkgPath: string): PackageFormat {
  if (!fs.existsSync(pkgPath)) {
    throw new Error(`Package path does not exist: ${pkgPath}`);
  }
  if (!fs.statSync(pkgPath).isDirectory()) {
    throw new Error(`Package path is not a directory: ${pkgPath}`);
  }

  if (hasMultiWorkflowLayout(pkgPath)) return "multi";
  if (fs.existsSync(path.join(pkgPath, "workflow.yaml"))) return "single";
  if (hasYamlFiles(pkgPath)) return "standalone";

  throw new Error(
    `No workflow files found in ${pkgPath}\n` +
      "Expected: workflow.yaml, workflows/*/workflow.yaml, or *.yaml files",
  );
}

function hasMultiWorkflowLayout(pkgPath: string): boolean {
  const workflowsDir = path.join(pkgPath, "workflows");
  if (!fs.existsSync(workflowsDir) || !fs.statSync(workflowsDir).isDirectory()) {
    return false;
  }
  return fs.readdirSync(workflowsDir).some((d) => {
    const subPath = path.join(workflowsDir, d);
    return (
      fs.statSync(subPath).isDirectory() &&
      fs.existsSync(path.join(subPath, "workflow.yaml"))
    );
  });
}

function hasYamlFiles(pkgPath: string): boolean {
  return fs.readdirSync(pkgPath).some(
    (f) => f.endsWith(".yaml") || f.endsWith(".yml"),
  );
}

// ---------------------------------------------------------------------------
// Manifest loading
// ---------------------------------------------------------------------------

export function loadManifest(pkgPath: string): PluginManifest | null {
  const jsonPath = path.join(pkgPath, "syntropic137-plugin.json");
  if (fs.existsSync(jsonPath)) {
    return parseManifestFile(jsonPath, "json");
  }

  const yamlPath = path.join(pkgPath, "syntropic137.yaml");
  if (fs.existsSync(yamlPath)) {
    return parseManifestFile(yamlPath, "yaml");
  }

  return null;
}

function parseManifestFile(filePath: string, format: "json" | "yaml"): PluginManifest {
  const content = fs.readFileSync(filePath, "utf-8");
  const data: unknown = format === "json" ? JSON.parse(content) : parseYaml(content);
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error(`${path.basename(filePath)} must be a ${format === "json" ? "JSON object" : "YAML mapping"}`);
  }
  return PluginManifestSchema.parse(data);
}

// ---------------------------------------------------------------------------
// Workflow resolution
// ---------------------------------------------------------------------------

function loadWorkflowYaml(
  workflowDir: string,
  sourcePath: string,
  phaseLibraryDir: string | null = null,
): ResolvedWorkflow {
  const yamlPath = path.join(workflowDir, "workflow.yaml");
  if (!fs.existsSync(yamlPath)) {
    throw new Error(`workflow.yaml not found in ${workflowDir}`);
  }
  return loadWorkflowYamlFromPath(yamlPath, sourcePath, phaseLibraryDir);
}

function loadWorkflowYamlFromPath(
  yamlPath: string,
  sourcePath: string,
  phaseLibraryDir: string | null = null,
): ResolvedWorkflow {
  const workflowDir = path.dirname(yamlPath);
  const content = fs.readFileSync(yamlPath, "utf-8");
  const data = parseYaml(content) as Record<string, unknown>;

  const phases = Array.isArray(data["phases"]) ? data["phases"] : [];
  const resolvedPhases = phases.map((phase) =>
    resolvePhase(phase as Record<string, unknown>, workflowDir, phaseLibraryDir),
  );

  const repository = data["repository"] as Record<string, unknown> | undefined;

  // The full document with resolved phases. Everything below this line is a
  // lossy projection of it; this is what actually gets uploaded.
  const definition: Record<string, unknown> = { ...data, phases: resolvedPhases };

  return {
    definition,
    id: String(data["id"] ?? ""),
    name: String(data["name"] ?? ""),
    workflow_type: String(data["type"] ?? data["workflow_type"] ?? "custom"),
    classification: String(data["classification"] ?? "standard"),
    repository_url: repository ? String(repository["url"] ?? "") : "",
    repository_ref: repository ? String(repository["ref"] ?? "main") : "main",
    description: data["description"] ? String(data["description"]) : null,
    project_name: data["project_name"] ? String(data["project_name"]) : null,
    requires_repos: inferRequiresRepos(data),
    phases: resolvedPhases as Record<string, unknown>[],
    input_declarations: parseInputDeclarations(data),
    source_path: sourcePath,
  };
}

const SHARED_PREFIX = "shared://";

/**
 * `fs.realpathSync` that reports "missing" instead of throwing.
 *
 * Containment checks must run against the REAL path: `path.resolve` only
 * normalizes segments, so a symlink inside the library that points at
 * `/etc/hosts` would sail through a purely lexical check. Python's
 * `Path.resolve()` follows links, so a lexical-only CLI check let a malicious
 * plugin upload host files that the domain would have rejected.
 */
function realPathOrNull(target: string): string | null {
  try {
    return fs.realpathSync(target);
  } catch {
    return null;
  }
}

function isContained(root: string, candidate: string): boolean {
  return candidate === root || candidate.startsWith(root + path.sep);
}

/**
 * Resolve a `shared://<name>` prompt reference to a file in `phase-library/`.
 *
 * WHY this lives in the CLI and not only in the domain: the server has no base
 * directory, so it rejects any `prompt_file` that still appears in an uploaded
 * document. The multi-workflow package format documents `shared://` as the way
 * to reuse a phase across workflows, so if the CLI does not inline it the
 * install fails with "prompt_file 'shared://x' was not resolved" and the
 * feature is unusable from `syn workflow install`.
 *
 * Mirrors `_resolve_shared_prompt_path` in the domain: a reference without a
 * phase library is an error, an empty name is an error, and the resolved path
 * must stay inside the library directory. Containment is checked both
 * lexically (catches `../..`) and after following symlinks (catches a link
 * planted inside the library), because the two are different attacks.
 */
function resolveSharedPromptPath(
  phaseId: string,
  ref: string,
  phaseLibraryDir: string | null,
): string {
  const name = ref.slice(SHARED_PREFIX.length);
  if (phaseLibraryDir === null) {
    throw new Error(
      `Phase '${phaseId}': shared:// reference '${ref}' requires a phase-library/ ` +
        `directory, which only the multi-workflow package format has`,
    );
  }
  if (!name) {
    throw new Error(`Phase '${phaseId}': shared:// reference is empty`);
  }

  const libRoot = realPathOrNull(phaseLibraryDir);
  if (libRoot === null) {
    throw new Error(
      `Phase '${phaseId}': shared:// reference '${ref}' does not exist ` +
        `(no phase-library directory at ${path.resolve(phaseLibraryDir)})`,
    );
  }

  const candidate = path.resolve(libRoot, `${name}.md`);
  // Lexical check first: a `../..` reference must report an escape even when
  // the target it points at does not exist.
  if (!isContained(libRoot, candidate)) {
    throw new Error(
      `Phase '${phaseId}': shared:// path '${name}' escapes the phase-library directory`,
    );
  }

  const resolved = realPathOrNull(candidate);
  if (resolved === null) {
    throw new Error(
      `Phase '${phaseId}': shared:// reference '${ref}' does not exist ` +
        `(looked for ${path.relative(libRoot, candidate)} in ${libRoot})`,
    );
  }
  if (!isContained(libRoot, resolved)) {
    throw new Error(
      `Phase '${phaseId}': shared:// path '${name}' escapes the phase-library directory`,
    );
  }
  return resolved;
}

/**
 * Resolve a relative `prompt_file` against the workflow directory.
 *
 * Mirrors `_resolve_local_prompt_path` in the domain: absolute paths are
 * rejected, and the resolved path must stay inside the base directory. Same
 * two-stage containment as `shared://` - lexical, then post-symlink.
 */
function resolveLocalPromptPath(
  phaseId: string,
  promptFile: string,
  baseDir: string,
): string {
  if (path.isAbsolute(promptFile)) {
    throw new Error(
      `Phase '${phaseId}': prompt_file must be a relative path, got: '${promptFile}'`,
    );
  }

  const base = realPathOrNull(baseDir) ?? path.resolve(baseDir);
  const candidate = path.resolve(base, promptFile);
  if (!isContained(base, candidate)) {
    throw new Error(
      `Phase '${phaseId}': prompt_file '${promptFile}' escapes base directory '${base}'`,
    );
  }

  const resolved = realPathOrNull(candidate);
  if (resolved === null) {
    throw new Error(
      `Phase '${phaseId}': prompt_file '${promptFile}' does not exist (looked for ${candidate})`,
    );
  }
  if (!isContained(base, resolved)) {
    throw new Error(
      `Phase '${phaseId}': prompt_file '${promptFile}' escapes base directory '${base}'`,
    );
  }
  return resolved;
}

/**
 * Mirrors `_resolve_phase_prompt_file` in the domain.
 *
 * Presence and null checks, never truthiness: the domain treats an explicit
 * falsy YAML value (`max_tokens: 0`, `prompt_template: ""`) as PRESENT, and a
 * falsy frontmatter value as a value worth merging. Truthiness here made the
 * CLI resolve documents the server then rejected, or ship documents whose
 * fields differed from what the domain would have produced.
 */
function resolvePhase(
  phase: Record<string, unknown>,
  workflowDir: string,
  phaseLibraryDir: string | null = null,
): Record<string, unknown> {
  if (!Object.hasOwn(phase, "prompt_file")) {
    return phase;
  }

  const phaseId = String(phase["id"] ?? "?");

  // The domain raises here rather than letting both fields reach validation.
  if (
    Object.hasOwn(phase, "prompt_template") &&
    phase["prompt_template"] !== null &&
    phase["prompt_template"] !== undefined
  ) {
    throw new Error(
      `Phase '${phaseId}': specify either 'prompt_template' or 'prompt_file', not both`,
    );
  }

  const promptFile = phase["prompt_file"];
  if (typeof promptFile !== "string") {
    throw new Error(
      `Phase '${phaseId}': prompt_file must be a string, got ${promptFile === null ? "null" : typeof promptFile}`,
    );
  }

  const promptPath = promptFile.startsWith(SHARED_PREFIX)
    ? resolveSharedPromptPath(phaseId, promptFile, phaseLibraryDir)
    : resolveLocalPromptPath(phaseId, promptFile, workflowDir);

  const promptContent = fs.readFileSync(promptPath, "utf-8");
  const { frontmatter, body } = parseFrontmatter(promptContent);
  const resolved: Record<string, unknown> = { ...phase };

  if (frontmatter) {
    mergeFrontmatter(resolved, frontmatter);
  }
  resolved["prompt_template"] = body;
  delete resolved["prompt_file"];
  return resolved;
}

/** Mirrors `_KEBAB_TO_SNAKE` in `md_prompt_loader`. */
const KEBAB_TO_SNAKE: Record<string, string> = {
  "argument-hint": "argument_hint",
  "allowed-tools": "allowed_tools",
  "execution-type": "execution_type",
  "max-tokens": "max_tokens",
  "timeout-seconds": "timeout_seconds",
};

/** Mirrors `normalize_frontmatter`: rename known keys, pass everything else through. */
function normalizeFrontmatter(fm: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(fm)) {
    const snakeKey = KEBAB_TO_SNAKE[key] ?? key;
    out[snakeKey] =
      snakeKey === "allowed_tools" && typeof value === "string"
        ? value.split(",").map((t) => t.trim()).filter((t) => t.length > 0)
        : value;
  }
  return out;
}

/**
 * Merge normalized frontmatter into the phase; explicit YAML values win.
 *
 * The domain's rule is `key not in phase or phase[key] is None`, so a phase
 * that explicitly sets `max_tokens: 0` keeps the 0 and a frontmatter value of
 * `0` or `""` is still merged. Truthiness got both of those backwards.
 */
function mergeFrontmatter(
  phase: Record<string, unknown>,
  fm: Record<string, unknown>,
): void {
  for (const [key, value] of Object.entries(normalizeFrontmatter(fm))) {
    if (!Object.hasOwn(phase, key) || phase[key] === null || phase[key] === undefined) {
      phase[key] = value;
    }
  }
}

function parseInputDeclarations(data: Record<string, unknown>): Array<{
  name: unknown;
  description: unknown;
  required: unknown;
  default: unknown;
}> {
  const inputs = Array.isArray(data["inputs"]) ? data["inputs"] : [];
  return inputs.map((i) => {
    const inp = i as Record<string, unknown>;
    return {
      name: inp["name"] ?? "",
      description: inp["description"] ?? "",
      required: inp["required"] ?? true,
      default: inp["default"] ?? null,
    };
  });
}

const FRONTMATTER_DELIMITER = "---";

function isDelimiterLine(line: string): boolean {
  return line.replace(/\r?\n$/, "") === FRONTMATTER_DELIMITER;
}

/** Line indices of the opening and closing `---`, or null if there is no frontmatter. */
function findDelimiters(lines: string[]): [number, number] | null {
  let open = 0;
  while (open < lines.length && lines[open]!.trim() === "") open += 1;
  if (open >= lines.length || !isDelimiterLine(lines[open]!)) return null;

  for (let close = open + 1; close < lines.length; close++) {
    if (isDelimiterLine(lines[close]!)) return [open, close];
  }
  return null;
}

/**
 * Mirrors `_split_frontmatter` / `_parse_md_prompt` in `md_prompt_loader`.
 *
 * Delimiters must be a line that is exactly `---`; `---extra` is body text, not
 * a delimiter. Leading blank lines are skipped. Both halves are trimmed. The
 * previous `indexOf("---", 3)` scan disagreed with the domain on every one of
 * those, and the body is what gets uploaded as `prompt_template`.
 */
function parseFrontmatter(content: string): {
  frontmatter: Record<string, unknown> | null;
  body: string;
} {
  const lines = content.split(/(?<=\n)/);
  const bounds = findDelimiters(lines);
  if (bounds === null) return { frontmatter: null, body: content.trim() };

  const [open, close] = bounds;
  const fm = parseYaml(lines.slice(open + 1, close).join(""));
  const body = lines.slice(close + 1).join("").trim();

  if (typeof fm === "object" && fm !== null && !Array.isArray(fm)) {
    return { frontmatter: fm as Record<string, unknown>, body };
  }
  // An empty block is `{}` to the domain; anything else that is not a mapping
  // is a ValueError there, so it must not be silently ignored here.
  if (fm === null) return { frontmatter: null, body };
  throw new Error(
    `YAML frontmatter must be a mapping, got ${Array.isArray(fm) ? "list" : typeof fm}`,
  );
}

// ---------------------------------------------------------------------------
// Package resolution (all formats)
// ---------------------------------------------------------------------------

function resolveMultiWorkflow(
  pkgPath: string,
  source: string,
): ResolvedWorkflow[] {
  const workflowsDir = path.join(pkgPath, "workflows");
  // Only the multi-workflow format has a phase library, so `shared://` is only
  // resolvable here. Passing the path even when the directory is absent keeps
  // the error message about the missing FILE rather than the missing feature.
  const phaseLibraryDir = path.join(pkgPath, "phase-library");
  const subdirs = fs
    .readdirSync(workflowsDir)
    .sort()
    .filter((d) => {
      const subPath = path.join(workflowsDir, d);
      return (
        fs.statSync(subPath).isDirectory() &&
        fs.existsSync(path.join(subPath, "workflow.yaml"))
      );
    });

  return subdirs.map((d) =>
    loadWorkflowYaml(path.join(workflowsDir, d), source, phaseLibraryDir),
  );
}

function resolveStandaloneYaml(
  pkgPath: string,
  source: string,
): ResolvedWorkflow[] {
  const files = fs
    .readdirSync(pkgPath)
    .filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"))
    .sort();

  return files.map((f) => {
    const filePath = path.join(pkgPath, f);
    const content = fs.readFileSync(filePath, "utf-8");
    const data = parseYaml(content) as Record<string, unknown>;
    const baseName = path.basename(f, path.extname(f));

    // Resolve prompt_file against the package dir for the same reason the
    // multi-workflow path does: the server has no base_dir and rejects an
    // unresolved ref, and this document is uploaded verbatim.
    const rawPhases = Array.isArray(data["phases"]) ? data["phases"] : [];
    const resolvedPhases = rawPhases.map((phase) =>
      resolvePhase(phase as Record<string, unknown>, pkgPath),
    ) as Record<string, unknown>[];

    return {
      definition: { ...data, phases: resolvedPhases },
      id: String(data["id"] ?? baseName),
      name: String(data["name"] ?? baseName),
      workflow_type: String(data["type"] ?? data["workflow_type"] ?? "custom"),
      classification: String(data["classification"] ?? "standard"),
      repository_url: "",
      repository_ref: "main",
      description: data["description"] ? String(data["description"]) : null,
      project_name: data["project_name"] ? String(data["project_name"]) : null,
      requires_repos: inferRequiresRepos(data),
      phases: resolvedPhases,
      input_declarations: [],
      source_path: source,
    };
  });
}

export function resolvePackage(
  pkgPath: string,
): { manifest: PluginManifest | null; workflows: ResolvedWorkflow[] } {
  const format = detectFormat(pkgPath);
  const manifest = loadManifest(pkgPath);
  const source = pkgPath;

  if (format === "single") {
    const workflow = loadWorkflowYaml(pkgPath, source);
    return { manifest, workflows: [workflow] };
  }

  if (format === "multi") {
    return { manifest, workflows: resolveMultiWorkflow(pkgPath, source) };
  }

  return { manifest, workflows: resolveStandaloneYaml(pkgPath, source) };
}

// ---------------------------------------------------------------------------
// Git source resolution
// ---------------------------------------------------------------------------

export async function resolveFromGit(
  url: string,
  ref: string,
): Promise<{
  tmpdir: string;
  manifest: PluginManifest | null;
  workflows: ResolvedWorkflow[];
  gitSha: string | null;
}> {
  const tmpdir = makeTempDir("syn-pkg-");
  try {
    await gitClone(url, ref, tmpdir);
  } catch (err) {
    removeTempDir(tmpdir);
    throw err;
  }

  // WHY (issue #822): this returned no sha, so explicit git URLs and
  // org/repo shorthand installed with no source_digest and the republish
  // check was silently inert for both. A policy that does not apply on two
  // of the resolution paths is not a policy.
  const gitSha = await gitHeadSha(tmpdir);
  const { manifest, workflows } = resolvePackage(tmpdir);
  return { tmpdir, manifest, workflows, gitSha };
}

// ---------------------------------------------------------------------------
// Scaffolding helpers
// ---------------------------------------------------------------------------

const PHASE_MD_TEMPLATE = (phaseNum: number | string, phaseName: string): string =>
  `---
model: sonnet
argument-hint: "[topic]"
allowed-tools: Read,Glob,Grep,Bash
max-tokens: 4096
timeout-seconds: 300
---

You are an AI assistant working on phase ${phaseNum}: ${phaseName}.

Your task: $ARGUMENTS

Work thoroughly and report your findings.
`;

function generatePhaseNames(workflowType: string, count: number): string[] {
  const presets: Record<string, string[]> = {
    research: ["Discovery", "Deep Dive", "Synthesis"],
    implementation: ["Research", "Plan", "Execute", "Review", "Ship"],
    review: ["Analyze", "Evaluate", "Report"],
    planning: ["Gather Context", "Design", "Validate"],
    deployment: ["Prepare", "Deploy", "Verify"],
  };
  const names = [...(presets[workflowType] ?? [])];
  while (names.length < count) {
    names.push(`Phase ${names.length + 1}`);
  }
  return names.slice(0, count);
}

export function scaffoldSinglePackage(
  directory: string,
  opts: { name: string; workflowType?: string; numPhases?: number },
): void {
  const workflowType = opts.workflowType ?? "research";
  const numPhases = opts.numPhases ?? 3;
  const phasesDir = path.join(directory, "phases");
  fs.mkdirSync(phasesDir, { recursive: true });

  const workflowId = opts.name.toLowerCase().replace(/ /g, "-") + "-v1";
  const phaseNames = generatePhaseNames(workflowType, numPhases);

  const phasesYamlLines: string[] = [];
  for (let i = 0; i < phaseNames.length; i++) {
    const phaseName = phaseNames[i]!;
    const phaseId = phaseName.toLowerCase().replace(/ /g, "-");
    fs.writeFileSync(
      path.join(phasesDir, `${phaseId}.md`),
      PHASE_MD_TEMPLATE(i + 1, phaseName),
      "utf-8",
    );
    phasesYamlLines.push(
      `  - id: ${phaseId}\n` +
        `    name: ${phaseName}\n` +
        `    order: ${i + 1}\n` +
        `    execution_type: sequential\n` +
        `    prompt_file: phases/${phaseId}.md\n` +
        `    output_artifacts: [${phaseId}_output]`,
    );
  }

  const workflowYaml =
    `id: ${workflowId}\n` +
    `name: ${opts.name}\n` +
    `description: "${opts.name} workflow"\n` +
    `type: ${workflowType}\n` +
    `classification: standard\n\n` +
    `inputs:\n` +
    `  - name: task\n` +
    `    description: "The primary task to accomplish"\n` +
    `    required: true\n\n` +
    `phases:\n` +
    phasesYamlLines.join("\n");

  fs.writeFileSync(path.join(directory, "workflow.yaml"), workflowYaml, "utf-8");

  const phaseList = phaseNames
    .map((pn, i) => `- **Phase ${i + 1}:** ${pn}`)
    .join("\n");
  const readme =
    `# ${opts.name}\n\n` +
    `${opts.name} workflow\n\n` +
    `## Usage\n\n` +
    "```bash\n" +
    `syn workflow install ./${path.basename(directory)}/\n` +
    `syn workflow run ${workflowId} --task "Your task here"\n` +
    "```\n\n" +
    `## Phases\n\n${phaseList}\n`;

  fs.writeFileSync(path.join(directory, "README.md"), readme, "utf-8");
}

export function scaffoldMultiPackage(
  directory: string,
  opts: { name: string; workflowType?: string; numPhases?: number },
): void {
  fs.mkdirSync(directory, { recursive: true });

  const manifest = {
    manifest_version: 1,
    name: opts.name.toLowerCase().replace(/ /g, "-"),
    version: "0.1.0",
    description: `${opts.name} plugin`,
  };
  fs.writeFileSync(
    path.join(directory, "syntropic137-plugin.json"),
    JSON.stringify(manifest, null, 2) + "\n",
    "utf-8",
  );

  const libDir = path.join(directory, "phase-library");
  fs.mkdirSync(libDir, { recursive: true });
  fs.writeFileSync(
    path.join(libDir, "summarize.md"),
    PHASE_MD_TEMPLATE("N", "Summarize"),
    "utf-8",
  );

  const wfName = opts.name.toLowerCase().replace(/ /g, "-");
  const wfDir = path.join(directory, "workflows", wfName);
  scaffoldSinglePackage(wfDir, opts);

  const readme =
    `# ${opts.name} Plugin\n\n` +
    `Plugin containing ${opts.name} workflows and shared phases\n\n` +
    `## Usage\n\n` +
    "```bash\n" +
    `syn workflow install ./${path.basename(directory)}/\n` +
    `syn workflow run ${wfName}-v1 --task "Your task here"\n` +
    "```\n\n" +
    `## Phases\n\n- **${opts.name}**: ${opts.numPhases ?? 3} phases\n`;

  fs.writeFileSync(path.join(directory, "README.md"), readme, "utf-8");
}
