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
