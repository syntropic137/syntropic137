/**
 * `syn skill` - the operator surface for registered skills (issue #826).
 *
 * Until this existed, nothing could answer "what skills are registered?": the
 * only lookup needed the exact (source_url, version, skill_name) triple, which
 * is what someone debugging a SkillNotRegistered failure does not have.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { listCommand } from "../../src/commands/skill/list.js";
import { showCommand } from "../../src/commands/skill/show.js";
import { addCommand } from "../../src/commands/skill/add.js";
import { CLIError } from "../../src/framework/errors.js";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
  vi.spyOn(process.stderr, "write").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  mockFetch.mockReset();
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stdout(): string {
  return (process.stdout.write as ReturnType<typeof vi.fn>).mock.calls
    .map((c: unknown[]) => String(c[0]))
    .join("");
}

const ENTRY = {
  skill_name: "repo-conventions",
  source_url: "https://github.com/example/skills",
  version: "v1.0.0",
  resolved_sha: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  resolved_sha_display: "abcdef012345",
  tree_storage_prefix: "skills/sha256-abcdef01",
  registered_at: "2026-08-17T12:00:00Z",
};

describe("syn skill list", () => {
  it("shows the identity triple, which is what makes a failure diagnosable", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ skills: [ENTRY], total: 1 }));

    await listCommand.handler({ positionals: [], values: {} });

    const out = stdout();
    expect(out).toContain("repo-conventions");
    expect(out).toContain("v1.0.0");
    expect(out).toContain("https://github.com/example/skills");
  });

  it("says plainly when nothing is registered rather than printing an empty table", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ skills: [], total: 0 }));

    await listCommand.handler({ positionals: [], values: {} });

    expect(stdout()).toMatch(/no skills/i);
  });

  it("emits json when asked, so an agent can consume it", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ skills: [ENTRY], total: 1 }));

    await listCommand.handler({ positionals: [], values: { json: true } });

    expect(JSON.parse(stdout()).skills[0].skill_name).toBe("repo-conventions");
  });
});

describe("syn skill show", () => {
  it("lists every registration of that name, since a name is not unique", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({
        skill_name: "repo-conventions",
        registrations: [ENTRY, { ...ENTRY, version: "v2.0.0" }],
      }),
    );

    await showCommand.handler({ positionals: ["repo-conventions"], values: {} });

    const out = stdout();
    expect(out).toContain("v1.0.0");
    expect(out).toContain("v2.0.0");
  });

  it("requires a name", async () => {
    await expect(showCommand.handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("reports an unregistered name as an error, not as empty output", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ detail: "not found" }, 404));

    await expect(
      showCommand.handler({ positionals: ["nope"], values: {} }),
    ).rejects.toThrow();
  });
});

describe("syn skill add", () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "skilladd-"));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("registers a local skill directory, pinned by its content hash", async () => {
    fs.writeFileSync(
      path.join(dir, "SKILL.md"),
      "---\nname: local-skill\ndescription: Use locally.\n---\n\nBody.\n",
    );
    mockFetch.mockResolvedValue(
      jsonResponse({ registered: false }),
    );
    mockFetch.mockResolvedValueOnce(jsonResponse({ registered: false }));
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ skill_name: "local-skill", resolved_sha: "deadbeef" }, 201),
    );

    await addCommand.handler({ positionals: [dir], values: {} });

    const postArg = mockFetch.mock.calls[1]![0];
    const url = postArg instanceof Request ? postArg.url : String(postArg);
    expect(url).toContain("/skills/registrations");
  });

  it("rejects an unpinned external ref, the same as a workflow install would", async () => {
    await expect(
      addCommand.handler({ positionals: ["anthropics/skills/foo@latest"], values: {} }),
    ).rejects.toThrow(/latest/i);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("requires a ref", async () => {
    await expect(addCommand.handler({ positionals: [], values: {} })).rejects.toThrow(CLIError);
  });

  it("skips the upload entirely when the content hash is already registered", async () => {
    fs.writeFileSync(
      path.join(dir, "SKILL.md"),
      "---\nname: local-skill\ndescription: Use locally.\n---\n\nBody.\n",
    );
    mockFetch.mockResolvedValue(jsonResponse({ registered: true, resolved_sha: "abc123" }));

    await addCommand.handler({ positionals: [dir], values: {} });

    // One lookup, no POST: the content hash is the cache.
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(stdout()).toMatch(/already registered/i);
  });

});

