/**
 * `syn workflow install` must upload the WHOLE resolved definition.
 *
 * It used to POST a hand-built JSON body to /workflows that named each field
 * explicitly, so anything the body did not name was dropped on install -
 * skills: and claude_plugins: among them. These tests assert the wire call:
 * the from-yaml endpoint, the declared id preserved as an override, and the
 * declared skills present in the uploaded bytes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installWorkflowsViaApi } from "../../../src/commands/workflow/install.js";
import type { ResolvedWorkflow } from "../../../src/packages/models.js";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
  vi.spyOn(process.stderr, "write").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function created(): Response {
  return new Response(
    JSON.stringify({
      id: "demo",
      name: "Demo",
      workflow_type: "research",
      classification: "simple",
      repository_url: "",
      requires_repos: false,
      status: "created",
    }),
    { status: 201, headers: { "Content-Type": "application/json" } },
  );
}

function workflow(definition: Record<string, unknown>): ResolvedWorkflow {
  return {
    definition,
    id: "demo",
    name: "Demo",
    workflow_type: "research",
    classification: "simple",
    repository_url: "",
    repository_ref: "main",
    description: null,
    project_name: null,
    requires_repos: false,
    phases: [],
    input_declarations: [],
    source_path: "/tmp/pkg",
  };
}

function lastCall(): { url: string; init: RequestInit } {
  const call = mockFetch.mock.calls[0]!;
  return { url: String(call[0]), init: call[1] as RequestInit };
}

function uploadedBody(init: RequestInit): string {
  const body = init.body;
  const bytes = body instanceof Uint8Array ? body : new Uint8Array(body as ArrayBuffer);
  return Buffer.from(bytes).toString("utf-8");
}

describe("installWorkflowsViaApi", () => {
  it("uploads to from-yaml, not the field-by-field JSON body", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })]);

    const { url, init } = lastCall();
    expect(url).toContain("/workflows/from-yaml");
    expect(init.method).toBe("POST");
  });

  it("carries declared skills through to the server", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([
      workflow({
        id: "demo",
        name: "Demo",
        skills: ["anthropics/skills/alpha@v1.0.0"],
        phases: [{ id: "one", name: "One", order: 1, skills: ["acme/skills/beta@v2.0.0"] }],
      }),
    ]);

    const body = uploadedBody(lastCall().init);
    expect(body).toContain("anthropics/skills/alpha@v1.0.0");
    expect(body).toContain("acme/skills/beta@v2.0.0");
  });

  it("preserves the yaml-declared id so re-installing does not duplicate", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })]);

    expect(lastCall().url).toContain("workflow_id=demo");
  });

  it("labels the body as JSON, which the from-yaml endpoint accepts as a YAML subset", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })]);

    const headers = lastCall().init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("reports a failed workflow instead of claiming it installed", async () => {
    mockFetch.mockResolvedValue(new Response("boom", { status: 400 }));

    await expect(
      installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })]),
    ).rejects.toThrow(/No workflows were installed/);
  });
});

describe("installWorkflowsViaApi partial failure", () => {
  it("fails loudly instead of reporting a half-installed package as success", async () => {
    // Previously the error was swallowed, the second workflow silently never
    // existed, and the command still printed "Installed 1 workflow(s)".
    mockFetch
      .mockResolvedValueOnce(created())
      .mockResolvedValueOnce(new Response("bad yaml", { status: 400 }));

    await expect(
      installWorkflowsViaApi([
        workflow({ id: "one", name: "One", phases: [] }),
        workflow({ id: "two", name: "Two", phases: [] }),
      ]),
    ).rejects.toThrow(/Failed to create workflow/);
  });

  it("names the workflows that were already created, since install is not transactional", async () => {
    mockFetch
      .mockResolvedValueOnce(created())
      .mockResolvedValueOnce(new Response("bad", { status: 400 }));

    await expect(
      installWorkflowsViaApi([
        workflow({ id: "one", name: "One", phases: [] }),
        workflow({ id: "two", name: "Two", phases: [] }),
      ]),
    ).rejects.toThrow(/remain installed/);
  });
});

describe("install provenance (issue #822)", () => {
  it("sends the package version and resolved digest", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })], {
      version: "0.3.0",
      sourceDigest: "abc123",
    });

    const { url } = lastCall();
    expect(url).toContain("version=0.3.0");
    expect(url).toContain("source_digest=abc123");
  });

  it("does not send force unless it was asked for", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })], {
      version: "0.3.0",
    });

    expect(lastCall().url).not.toContain("force");
  });

  it("sends force when set", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })], {
      version: "0.3.0",
      force: true,
    });

    expect(lastCall().url).toContain("force=true");
  });

  it("omits the digest for a local install that has no resolved commit", async () => {
    mockFetch.mockResolvedValue(created());

    await installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })], {
      version: "0.3.0",
      sourceDigest: null,
    });

    expect(lastCall().url).not.toContain("source_digest");
  });

  it("surfaces the server's 409 refusal rather than a generic failure", async () => {
    mockFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Workflow 'demo' version 0.3.0 is already installed. Pass --force to reinstall it.",
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(
      installWorkflowsViaApi([workflow({ id: "demo", name: "Demo", phases: [] })], {
        version: "0.3.0",
      }),
    ).rejects.toThrow(/already installed/);
  });
});

describe("unchanged reinstall (issue #822)", () => {
  it("reports an identical reinstall as already installed, not as a failure", async () => {
    mockFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "demo",
          name: "Demo",
          workflow_type: "research",
          classification: "simple",
          repository_url: "",
          requires_repos: false,
          status: "unchanged",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    const refs = await installWorkflowsViaApi(
      [workflow({ id: "demo", name: "Demo", phases: [] })],
      { version: "0.3.0", sourceDigest: "aaa111" },
    );

    // Still counted as installed: it is present and current, which is what a
    // caller rerunning the command needs to know.
    expect(refs).toEqual([{ id: "demo", name: "Demo" }]);
  });
});
