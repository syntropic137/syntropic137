/**
 * Raw-body YAML upload helper for `POST /workflows/from-yaml`.
 *
 * openapi-fetch cannot type raw-body requests, so this is the one
 * escape-hatch endpoint that bypasses the typed client. Every semantic
 * field of the workflow lives in the YAML body; `name` and `workflowId`
 * may be supplied as query-string overrides, and `version`, `sourceDigest`
 * and `force` carry install provenance and policy (issue #822).
 */

import type { components } from "../generated/api-types.js";
import { CLIError } from "../framework/errors.js";
import { getApiUrl, getAuthHeaders } from "../config.js";
import { API_PREFIX } from "./constants.js";

export type CreateWorkflowResponse = components["schemas"]["CreateWorkflowResponse"];

export interface PostYamlOptions {
  name?: string;
  workflowId?: string;
  /**
   * Body media type. Defaults to YAML (`create --from` uploads file bytes).
   *
   * `workflow install` passes "application/json": it uploads a definition it
   * resolved and re-serialized rather than the original file, and JSON is a
   * YAML subset that it can emit without a YAML writer.
   */
  contentType?: "application/yaml" | "application/json";
  /** Label used in the error message, so failures name the command that failed. */
  errorLabel?: string;
  /**
   * Package version being installed (issue #822). The server records it and
   * refuses a reinstall of a version already installed unless `force` is set.
   * Omitting it on a package that declares one is refused outright, because
   * that would erase the provenance the digest check depends on.
   */
  version?: string;
  /**
   * Resolved source commit SHA for the package content (issue #822). The
   * server refuses a matching version that resolves to a different digest:
   * that is the signature of a republished version, which a version check
   * alone would not catch.
   */
  sourceDigest?: string;
  /** Explicit intent to overwrite an already-installed matching version. */
  force?: boolean;
}

export async function postYaml(
  fileBytes: Buffer,
  options: PostYamlOptions = {},
): Promise<CreateWorkflowResponse> {
  const baseUrl = getApiUrl().replace(/\/+$/, "");
  const url = new URL(`${baseUrl}${API_PREFIX}/workflows/from-yaml`);
  if (options.name) url.searchParams.set("name", options.name);
  if (options.workflowId) url.searchParams.set("workflow_id", options.workflowId);
  if (options.version) url.searchParams.set("version", options.version);
  if (options.sourceDigest) url.searchParams.set("source_digest", options.sourceDigest);
  if (options.force) url.searchParams.set("force", "true");

  const response = await globalThis.fetch(url.toString(), {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": options.contentType ?? "application/yaml",
    },
    body: new Uint8Array(fileBytes),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new CLIError(
      `${options.errorLabel ?? "workflow create --from"} failed (${response.status}): ` +
        `${text || response.statusText}`,
    );
  }

  return (await response.json()) as CreateWorkflowResponse;
}
