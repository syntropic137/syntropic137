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
      "Content-Type": "application/yaml",
    },
    body: new Uint8Array(fileBytes),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new CLIError(
      `workflow create --from failed (${response.status}): ${text || response.statusText}`,
    );
  }

  return (await response.json()) as CreateWorkflowResponse;
}
