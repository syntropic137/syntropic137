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

    // Identity BEFORE content, so a remote skill that is already registered
    // costs one lookup and no clone. A bundled ref is the exception: its
    // version IS its tree hash, so its files must be read to know what it is.
    const identity = await resolveIdentity(raw);

    if (await isRegistered(identity.ref)) {
      printDim(`  skill ${identity.ref.skillName}@${identity.ref.version} already registered`);
      return;
    }

    const ref = identity.ref;
    const files = identity.files ?? (await fetchRemoteTree(ref));

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
 * Determine a skill's identity from a CLI argument.
 *
 * A local directory is a bundled skill: it has no version of its own, so it is
 * pinned by the sha256 of its tree, exactly as `syn workflow install` pins one.
 * That requires reading the files, so they come back too. A remote ref carries
 * its own version, so its identity is known without any network work.
 */
async function resolveIdentity(
  raw: string,
): Promise<{ ref: ExternalSkillRef; files?: SkillFilePayload[] }> {
  if (isLocalDir(raw)) {
    // WHY the reference is used verbatim rather than reduced to a basename:
    // the bundled source_url IS part of the identity triple that run-time
    // resolution looks up, and a workflow declaring `./skills/foo` pins
    // exactly that string. Registering `./foo` instead would store an identity
    // no workflow can ever resolve, which makes this command worse than
    // useless - it reports success and the run still fails.
    if (!raw.startsWith("./") && !raw.startsWith("../")) {
      throw new CLIError(
        `local skill path must be relative, as a workflow would declare it: ${raw}\n` +
          "  A workflow pins the path it declares (for example './skills/foo'), and that\n" +
          "  exact string is part of the skill's identity. An absolute path cannot be\n" +
          "  matched to a workflow declaration, so registering one would be unusable.",
      );
    }
    const files = readSkillTree(path.resolve(raw));
    const parsed = parseSkillEntry(raw)[0]!;
    if (parsed.kind !== "bundled") {
      throw new CLIError(`expected a bundled ref for a local path: ${raw}`);
    }
    return { ref: pinBundledRef(parsed, files), files };
  }

  const parsed = parseSkillEntry(raw)[0]!;
  if (parsed.kind === "bundled") {
    throw new CLIError(`no such directory: ${raw}`);
  }
  return { ref: parsed };
}

/** Clone a pinned remote ref and read the skill tree out of it. */
async function fetchRemoteTree(parsed: ExternalSkillRef): Promise<SkillFilePayload[]> {
  const tmpdir = makeTempDir("syn-skill-");
  try {
    print(`Cloning ${style(parsed.sourceUrl, CYAN)}@${parsed.version}...`);
    await gitClone(parsed.sourceUrl, parsed.version, tmpdir);
    try {
      return readSkillTree(skillDirInClone(tmpdir, parsed.skillName));
    } catch (err) {
      // The shared locator throws a plain Error; without this the CLI reports
      // "Unexpected error" and exit code 2 for what is an ordinary, actionable
      // user mistake (wrong skill name for that repo).
      throw new CLIError(err instanceof Error ? err.message : String(err));
    }
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
