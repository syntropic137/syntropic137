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
import { gitClone, makeTempDir, removeTempDir } from "./git.js";
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
  saveInstalled({
    version: registry.version,
    installations: [...registry.installations, record],
  });
}

// ---------------------------------------------------------------------------
// Source parsing
// ---------------------------------------------------------------------------

export function parseSource(source: string): { resolved: string; isRemote: boolean } {
  if (
    source.startsWith("https://") ||
    source.startsWith("http://") ||
    source.startsWith("git@") ||
    source.startsWith("ssh://")
  ) {
    return { resolved: source, isRemote: true };
  }

  if (
    fs.existsSync(source) ||
    source.startsWith(".") ||
    source.startsWith("/")
  ) {
    return { resolved: source, isRemote: false };
  }

  if (source.includes("/") && !source.includes("@") && !source.startsWith(".")) {
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

  // Multi-workflow: workflows/*/workflow.yaml
  const workflowsDir = path.join(pkgPath, "workflows");
  if (fs.existsSync(workflowsDir) && fs.statSync(workflowsDir).isDirectory()) {
    const subdirs = fs.readdirSync(workflowsDir);
    const hasWorkflow = subdirs.some((d) => {
      const subPath = path.join(workflowsDir, d);
      return (
        fs.statSync(subPath).isDirectory() &&
        fs.existsSync(path.join(subPath, "workflow.yaml"))
      );
    });
    if (hasWorkflow) return "multi";
  }

  // Single workflow: workflow.yaml at root
  if (fs.existsSync(path.join(pkgPath, "workflow.yaml"))) {
    return "single";
  }

  // Standalone YAML
  const files = fs.readdirSync(pkgPath);
  const yamlFiles = files.filter(
    (f) => f.endsWith(".yaml") || f.endsWith(".yml"),
  );
  if (yamlFiles.length > 0) return "standalone";

  throw new Error(
    `No workflow files found in ${pkgPath}\n` +
      "Expected: workflow.yaml, workflows/*/workflow.yaml, or *.yaml files",
  );
}

// ---------------------------------------------------------------------------
// Manifest loading
// ---------------------------------------------------------------------------

export function loadManifest(pkgPath: string): PluginManifest | null {
  const jsonPath = path.join(pkgPath, "syntropic137-plugin.json");
  if (fs.existsSync(jsonPath)) {
    const content = fs.readFileSync(jsonPath, "utf-8");
    const data: unknown = JSON.parse(content);
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      throw new Error("syntropic137-plugin.json must be a JSON object");
    }
    return PluginManifestSchema.parse(data);
  }

  const yamlPath = path.join(pkgPath, "syntropic137.yaml");
  if (fs.existsSync(yamlPath)) {
    const content = fs.readFileSync(yamlPath, "utf-8");
    const data = parseYaml(content);
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      throw new Error("syntropic137.yaml must be a YAML mapping");
    }
    return PluginManifestSchema.parse(data);
  }

  return null;
}

// ---------------------------------------------------------------------------
// Workflow resolution
// ---------------------------------------------------------------------------

function loadWorkflowYaml(
  workflowDir: string,
  sourcePath: string,
): ResolvedWorkflow {
  const yamlPath = path.join(workflowDir, "workflow.yaml");
  if (!fs.existsSync(yamlPath)) {
    throw new Error(`workflow.yaml not found in ${workflowDir}`);
  }

  const content = fs.readFileSync(yamlPath, "utf-8");
  const data = parseYaml(content) as Record<string, unknown>;

  const phases = Array.isArray(data["phases"]) ? data["phases"] : [];
  const resolvedPhases = phases.map((phase) => {
    const p = phase as Record<string, unknown>;
    // Resolve prompt_file references
    if (typeof p["prompt_file"] === "string" && !p["prompt_template"]) {
      const promptPath = path.join(workflowDir, p["prompt_file"] as string);
      if (fs.existsSync(promptPath)) {
        const promptContent = fs.readFileSync(promptPath, "utf-8");
        const { frontmatter, body } = parseFrontmatter(promptContent);
        const resolved: Record<string, unknown> = { ...p, prompt_template: body };
        delete resolved["prompt_file"];
        // Merge frontmatter (YAML values take precedence)
        if (frontmatter) {
          if (frontmatter["argument-hint"] && !resolved["argument_hint"]) {
            resolved["argument_hint"] = frontmatter["argument-hint"];
          }
          if (frontmatter["allowed-tools"] && !resolved["allowed_tools"]) {
            const tools = String(frontmatter["allowed-tools"]);
            resolved["allowed_tools"] = tools.split(",").map((t) => t.trim());
          }
          if (frontmatter["max-tokens"] && !resolved["max_tokens"]) {
            resolved["max_tokens"] = Number(frontmatter["max-tokens"]);
          }
          if (frontmatter["timeout-seconds"] && !resolved["timeout_seconds"]) {
            resolved["timeout_seconds"] = Number(frontmatter["timeout-seconds"]);
          }
          if (frontmatter["model"] && !resolved["model"]) {
            resolved["model"] = frontmatter["model"];
          }
        }
        return resolved;
      }
    }
    return p;
  });

  const inputs = Array.isArray(data["inputs"]) ? data["inputs"] : [];
  const inputDecls = inputs.map((i) => {
    const inp = i as Record<string, unknown>;
    return {
      name: inp["name"] ?? "",
      description: inp["description"] ?? "",
      required: inp["required"] ?? true,
      default: inp["default"] ?? null,
    };
  });

  const repository = data["repository"] as Record<string, unknown> | undefined;

  return {
    id: String(data["id"] ?? ""),
    name: String(data["name"] ?? ""),
    workflow_type: String(data["type"] ?? data["workflow_type"] ?? "custom"),
    classification: String(data["classification"] ?? "standard"),
    repository_url: repository
      ? String(repository["url"] ?? "https://github.com/placeholder/not-configured")
      : "https://github.com/placeholder/not-configured",
    repository_ref: repository ? String(repository["ref"] ?? "main") : "main",
    description: data["description"] ? String(data["description"]) : null,
    project_name: data["project_name"] ? String(data["project_name"]) : null,
    phases: resolvedPhases as Record<string, unknown>[],
    input_declarations: inputDecls,
    source_path: sourcePath,
  };
}

function parseFrontmatter(content: string): {
  frontmatter: Record<string, unknown> | null;
  body: string;
} {
  if (!content.startsWith("---")) {
    return { frontmatter: null, body: content };
  }

  const endIdx = content.indexOf("---", 3);
  if (endIdx === -1) {
    return { frontmatter: null, body: content };
  }

  const fmContent = content.slice(3, endIdx).trim();
  const body = content.slice(endIdx + 3).trim();
  const fm = parseYaml(fmContent);

  return {
    frontmatter:
      typeof fm === "object" && fm !== null && !Array.isArray(fm)
        ? (fm as Record<string, unknown>)
        : null,
    body,
  };
}

// ---------------------------------------------------------------------------
// Package resolution (all formats)
// ---------------------------------------------------------------------------

function resolveMultiWorkflow(
  pkgPath: string,
  source: string,
): ResolvedWorkflow[] {
  const workflowsDir = path.join(pkgPath, "workflows");
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
    loadWorkflowYaml(path.join(workflowsDir, d), source),
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

    return {
      id: String(data["id"] ?? baseName),
      name: String(data["name"] ?? baseName),
      workflow_type: String(data["type"] ?? data["workflow_type"] ?? "custom"),
      classification: String(data["classification"] ?? "standard"),
      repository_url: "https://github.com/placeholder/not-configured",
      repository_ref: "main",
      description: data["description"] ? String(data["description"]) : null,
      project_name: data["project_name"] ? String(data["project_name"]) : null,
      phases: Array.isArray(data["phases"])
        ? (data["phases"] as Record<string, unknown>[])
        : [],
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
}> {
  const tmpdir = makeTempDir("syn-pkg-");
  try {
    await gitClone(url, ref, tmpdir);
  } catch (err) {
    removeTempDir(tmpdir);
    throw err;
  }

  const { manifest, workflows } = resolvePackage(tmpdir);
  return { tmpdir, manifest, workflows };
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
    `## Phases\n\n- **${opts.name}** — ${opts.numPhases ?? 3} phases\n`;

  fs.writeFileSync(path.join(directory, "README.md"), readme, "utf-8");
}
