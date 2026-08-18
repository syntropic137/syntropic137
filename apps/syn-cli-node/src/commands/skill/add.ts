/**
 * `syn skill add <ref>` - register a skill without a workflow install.
 *
 * WHY this exists separately from the install preflight: registering a skill
 * used to require a hand-built `POST /skills/registrations` with a base64 file
 * tree. This is the same resolve-and-register path the preflight uses, so a
 * ref that works here works in a workflow, and vice versa.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import type { CommandDef, ParsedArgs } from "../../framework/command.js";
import { CLIError } from "../../framework/errors.js";
import { api, unwrap } from "../../client/typed.js";
import { printError, printSuccess, printDim, print } from "../../output/console.js";
import { style, CYAN } from "../../output/ansi.js";
import { gitClone, makeTempDir, removeTempDir } from "../../packages/git.js";
import {
  parseSkillEntry,
  pinBundledRef,
  type ExternalSkillRef,
} from "../../packages/skill-ref.js";
import {
  readSkillTree,
  skillDirInClone,
  type SkillFilePayload,
} from "../../packages/skill-tree.js";

export const addCommand: CommandDef = {
  name: "add",
  description: "Register a skill from a local path or a pinned remote ref",
  args: [
    {
      name: "ref",
      description: "Local path, or org/repo/skill@version, or <url>@<version>",
      required: true,
    },
  ],
  handler: async (parsed: ParsedArgs) => {
    const raw = parsed.positionals[0];
    if (!raw) {
      printError("Missing required argument: ref");
      throw new CLIError("Missing argument", 1);
    }

    const { ref, files } = await resolveRef(raw);

    const registered = await isRegistered(ref);
    if (registered) {
      printDim(`  skill ${ref.skillName}@${ref.version} already registered`);
      return;
    }

    const result = unwrap(
      await api.POST("/skills/registrations", {
        body: {
          source_url: ref.sourceUrl,
          version: ref.version,
          skill_name: ref.skillName,
          files: files as { rel_path: string; content_base64: string }[],
        },
      }),
      `Failed to register skill ${ref.skillName}`,
    );

    printSuccess(`Registered ${style(ref.skillName, CYAN)}@${ref.version}`);
    print(`  Sha: ${result.resolved_sha}`);
  },
};

/**
 * Turn a CLI argument into a pinned ref plus its file tree.
 *
 * A local directory is treated as a bundled skill: it has no version of its
 * own, so it is pinned by the sha256 of its tree, exactly as a plugin-bundled
 * skill is during `syn workflow install`.
 */
async function resolveRef(
  raw: string,
): Promise<{ ref: ExternalSkillRef; files: SkillFilePayload[] }> {
  if (isLocalDir(raw)) {
    const dir = path.resolve(raw);
    const files = readSkillTree(dir);
    const parsed = parseSkillEntry(`./${path.basename(dir)}`)[0]!;
    if (parsed.kind !== "bundled") {
      throw new CLIError(`expected a bundled ref for a local path: ${raw}`);
    }
    return { ref: pinBundledRef(parsed, files), files };
  }

  const parsed = parseSkillEntry(raw)[0]!;
  if (parsed.kind === "bundled") {
    throw new CLIError(`no such directory: ${raw}`);
  }

  const tmpdir = makeTempDir("syn-skill-");
  try {
    print(`Cloning ${style(parsed.sourceUrl, CYAN)}@${parsed.version}...`);
    await gitClone(parsed.sourceUrl, parsed.version, tmpdir);
    return { ref: parsed, files: readSkillTree(skillDirInClone(tmpdir, parsed.skillName)) };
  } finally {
    removeTempDir(tmpdir);
  }
}

function isLocalDir(raw: string): boolean {
  try {
    return fs.statSync(raw).isDirectory();
  } catch {
    return false;
  }
}


async function isRegistered(ref: ExternalSkillRef): Promise<boolean> {
  const data = unwrap(
    await api.GET("/skills/registrations", {
      params: {
        query: {
          source_url: ref.sourceUrl,
          version: ref.version,
          skill_name: ref.skillName,
        },
      },
    }),
    `Failed to look up skill ${ref.skillName}@${ref.version}`,
  );
  return Boolean(data.registered);
}
