/** Retrieve one immutable local capture without requiring a remote session store. */
import { createHash } from "node:crypto";
import { api, unwrap } from "../client/typed.js";
import type { CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { print } from "../output/console.js";

export const executionTranscriptCommand: CommandDef = {
  name: "transcript",
  description: "Read an exact local transcript archive revision",
  args: [
    { name: "execution-id", description: "Execution ID or unique prefix", required: true },
    { name: "harness", description: "Native harness namespace", required: true },
    { name: "native-id", description: "Full native session ID", required: true },
    { name: "revision", description: "Archive SHA-256 from capture evidence", required: true },
  ],
  options: {
    raw: { type: "boolean", description: "Write verified archive bytes to stdout" },
    json: { type: "boolean", description: "Print metadata and base64 archive bytes as JSON" },
  },
  handler: async ({ positionals, values }) => {
    const [execution, harness, nativeId, revision] = positionals;
    if (!execution || !harness?.trim() || !nativeId?.trim() || !revision || !/^[a-f0-9]{64}$/.test(revision)) {
      throw new CLIError("execution-id, harness, native-id and a lowercase archive SHA-256 are required");
    }
    if (values["raw"] === true && values["json"] === true) throw new CLIError("raw and json cannot be combined");
    const result = unwrap(await api.GET("/executions/{execution_id}/session-transcripts/{archive_hash}", {
      params: { path: { execution_id: execution, archive_hash: revision }, query: { harness, native_id: nativeId } },
    }), "Failed to read local transcript");
    if (result.archive_sha256 !== revision) throw new CLIError("Transcript revision mismatch");
    if (result.status !== "present") {
      if (values["json"] === true) print(JSON.stringify(result));
      throw new CLIError(`Transcript unavailable: ${result.status}`);
    }
    if (typeof result.content_base64 !== "string" || result.content_base64.length > 22369624) throw new CLIError("Invalid transcript body");
    const body = Buffer.from(result.content_base64, "base64");
    if (body.toString("base64") !== result.content_base64 || body.length !== result.size || createHash("sha256").update(body).digest("hex") !== revision) {
      throw new CLIError("Transcript integrity verification failed");
    }
    if (values["raw"] === true) process.stdout.write(body);
    else if (values["json"] === true) print(JSON.stringify(result));
    else print(`${result.content_format}\t${body.length} bytes\t${revision}`);
  },
};
