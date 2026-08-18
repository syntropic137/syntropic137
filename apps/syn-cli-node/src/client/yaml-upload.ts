/**
 * Raw-body YAML upload helper for `POST /workflows/from-yaml`.
 *
 * openapi-fetch cannot type raw-body requests, so this is the one
 * escape-hatch endpoint that bypasses the typed client. Every semantic
 * field of the workflow lives in the YAML body; only `name` and
 * `workflowId` may be supplied as query-string overrides.
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
}

export async function postYaml(
  fileBytes: Buffer,
  options: PostYamlOptions = {},
): Promise<CreateWorkflowResponse> {
  const baseUrl = getApiUrl().replace(/\/+$/, "");
  const url = new URL(`${baseUrl}${API_PREFIX}/workflows/from-yaml`);
  if (options.name) url.searchParams.set("name", options.name);
  if (options.workflowId) url.searchParams.set("workflow_id", options.workflowId);

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
