/**
 * Typed response models and helpers for workflow API responses.
 * Port of apps/syn-cli/src/syn_cli/commands/_workflow_models.py
 */

export interface WorkflowSummary {
  id: string;
  name: string;
  workflow_type: string;
  phase_count: number;
}

export interface WorkflowDetail {
  id: string;
  name: string;
  workflow_type: string;
  classification: string;
  phases: Record<string, unknown>[];
}

export interface ExecutionRunResponse {
  status: string;
  execution_id: string;
}

function isQuoted(value: string): boolean {
  return value.length >= 2 && value[0] === value[value.length - 1] && (value[0] === '"' || value[0] === "'");
}

function coerceValue(value: string): string | number {
  if (/^-?\d+$/.test(value)) return parseInt(value, 10);
  if (/^-?\d+\.\d+$/.test(value)) return parseFloat(value);
  return value;
}

function parseSingleValue(value: string): string | number | boolean {
  if (isQuoted(value)) return value.slice(1, -1);
  const lower = value.toLowerCase();
  if (lower === "true") return true;
  if (lower === "false") return false;
  return coerceValue(value);
}

export function parseInputs(
  inputs: readonly string[] | undefined,
): Record<string, string | number | boolean> {
  if (!inputs || inputs.length === 0) return {};

  const result: Record<string, string | number | boolean> = {};
  for (const item of inputs) {
    const eqIdx = item.indexOf("=");
    if (eqIdx === -1) {
      process.stderr.write(`Warning: Ignoring invalid input '${item}' (expected key=value)\n`);
      continue;
    }
    const key = item.slice(0, eqIdx).trim();
    const value = item.slice(eqIdx + 1);
    result[key] = parseSingleValue(value);
  }
  return result;
}
