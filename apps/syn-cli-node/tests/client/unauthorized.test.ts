/**
 * A 401 names the deployment, the user that was sent, and where credentials
 * come from - never the password (#1571). Each case goes through a real typed
 * client and `unwrap`, so what is asserted is the message a command throws,
 * whichever body the gateway answered with.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { streamSSE } from "../../src/client/sse.js";
import { createTypedClient, unwrap } from "../../src/client/typed.js";
import { postYaml } from "../../src/client/yaml-upload.js";

const DEPLOYMENT = "http://syn.example:8137";
const USER = "operator-7f3a";
const PASSWORD = "rotated-pw-91c2";
const TOKEN = "tok-5d0e";

/** What the gateway's API locations answer since #1571. */
const jsonUnauthorized = (): Response =>
  new Response(
    JSON.stringify({ detail: "unauthorized", hint: "check SYN_API_USER / SYN_API_PASSWORD for this deployment" }),
    { status: 401, headers: { "Content-Type": "application/json", "WWW-Authenticate": 'Basic realm="Syntropic137"' } },
  );

/** What an older gateway answers: nginx's built-in page. */
const htmlUnauthorized = (): Response =>
  new Response(
    "<html>\r\n<head><title>401 Authorization Required</title></head>\r\n<body>\r\n<center><h1>401 Authorization Required</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n",
    { status: 401, headers: { "Content-Type": "text/html", "WWW-Authenticate": 'Basic realm="Syntropic137"' } },
  );

async function typedError(answer: () => Response): Promise<string> {
  vi.stubGlobal("fetch", async () => answer());
  const result = await createTypedClient().GET("/workflows", {});
  expect(result.response.status).toBe(401);
  try {
    unwrap(result, "Failed to list workflows");
  } catch (err) {
    return (err as Error).message;
  }
  throw new Error("unwrap did not throw");
}

function useBasic(): void {
  vi.stubEnv("SYN_API_URL", DEPLOYMENT);
  vi.stubEnv("SYN_API_USER", USER);
  vi.stubEnv("SYN_API_PASSWORD", PASSWORD);
}

describe("a 401 from the API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it.each([
    ["JSON", jsonUnauthorized],
    ["HTML", htmlUnauthorized],
  ])("names the URL, the user sent and the credential sources for a %s body", async (_kind, answer) => {
    useBasic();
    const message = await typedError(answer);
    expect(message).toBe(
      `Failed to list workflows: ${DEPLOYMENT} answered 401 Unauthorized to Basic auth as user "${USER}". ` +
        "Credentials come from SYN_API_TOKEN (bearer) or SYN_API_USER + SYN_API_PASSWORD (Basic); " +
        "run `syn config show` to see what this CLI is sending.",
    );
    expect(message).not.toContain(PASSWORD);
    expect(message).not.toMatch(/<html|Authorization Required/);
  });

  it("says a bearer token was sent, without the token", async () => {
    vi.stubEnv("SYN_API_URL", DEPLOYMENT);
    vi.stubEnv("SYN_API_TOKEN", TOKEN);
    const message = await typedError(jsonUnauthorized);
    expect(message).toContain("a bearer token from SYN_API_TOKEN");
    expect(message).not.toContain(TOKEN);
  });

  it("says nothing was sent when the user has no password", async () => {
    vi.stubEnv("SYN_API_URL", DEPLOYMENT);
    vi.stubEnv("SYN_API_USER", USER);
    const message = await typedError(htmlUnauthorized);
    expect(message).toContain(`no credentials (SYN_API_USER is "${USER}" but SYN_API_PASSWORD is not set)`);
  });

  it("explains syn-api's own 401 too, and leaves other statuses to the server's detail", async () => {
    useBasic();
    const message = await typedError(() => new Response(JSON.stringify({ detail: "nope" }), { status: 401 }));
    expect(message).not.toContain("nope");
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "forbidden here" }), { status: 403 }));
    const result = await createTypedClient().GET("/workflows", {});
    expect(() => unwrap(result, "x")).toThrow("x: forbidden here");
  });

  it("explains a 401 on the raw YAML upload too", async () => {
    useBasic();
    vi.stubGlobal("fetch", async () => htmlUnauthorized());
    const failure = postYaml(Buffer.from("name: w\n")).catch((err: Error) => err.message);
    const message = await failure;
    expect(message).toContain(`${DEPLOYMENT} answered 401 Unauthorized to Basic auth as user "${USER}"`);
    expect(message).not.toContain(PASSWORD);
  });

  it("explains a 401 on an SSE stream instead of parsing the page as events", async () => {
    useBasic();
    vi.stubGlobal("fetch", async () => htmlUnauthorized());
    const stream = streamSSE("/sse/activity");
    await expect(stream.next()).rejects.toThrow(
      `${DEPLOYMENT} answered 401 Unauthorized to Basic auth as user "${USER}"`,
    );
  });
});
