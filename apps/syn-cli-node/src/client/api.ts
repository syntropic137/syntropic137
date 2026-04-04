import { getApiUrl } from "../config.js";
import { CLIError } from "../framework/errors.js";
import { printDim, printError } from "../output/console.js";
import { SynClient } from "./http.js";

function handleConnectError(): never {
  printError(`Could not connect to API at ${getApiUrl()}`);
  printDim("Make sure the API server is running.");
  throw new CLIError("Connection failed", 1);
}

function checkResponse(
  status: number,
  data: unknown,
  expected: readonly number[],
): void {
  if (expected.includes(status)) return;

  let detail = `HTTP ${status}`;
  if (
    typeof data === "object" &&
    data !== null &&
    "detail" in data &&
    typeof (data as { detail: unknown }).detail === "string"
  ) {
    detail = (data as { detail: string }).detail;
  }

  throw new CLIError(detail);
}

async function safeRequest<T>(
  fn: () => Promise<T>,
): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof CLIError) throw err;
    handleConnectError();
  }
}

export async function apiGet<T = Record<string, unknown>>(
  path: string,
  options?: {
    params?: Record<string, string | number | boolean | undefined>;
    expected?: readonly number[];
  },
): Promise<T> {
  const client = new SynClient();
  const { status, data } = await safeRequest(() =>
    client.get<T>(path, options?.params),
  );
  checkResponse(status, data, options?.expected ?? [200]);
  return data;
}

export async function apiGetList<T = Record<string, unknown>>(
  path: string,
  options?: {
    params?: Record<string, string | number | boolean | undefined>;
    expected?: readonly number[];
  },
): Promise<T[]> {
  const client = new SynClient();
  const { status, data } = await safeRequest(() =>
    client.get<T[]>(path, options?.params),
  );
  checkResponse(status, data, options?.expected ?? [200]);
  return data;
}

export async function apiGetPaginated<T = Record<string, unknown>>(
  path: string,
  key: string,
  options?: {
    params?: Record<string, string | number | boolean | undefined>;
    expected?: readonly number[];
  },
): Promise<T[]> {
  const client = new SynClient();
  const { status, data } = await safeRequest(() =>
    client.get<Record<string, unknown>>(path, options?.params),
  );
  checkResponse(status, data, options?.expected ?? [200]);
  if (typeof data !== "object" || data === null) {
    throw new CLIError(`Unexpected API response for "${path}": expected an object containing "${key}".`);
  }
  const items = data[key];
  if (!Array.isArray(items)) {
    throw new CLIError(`Unexpected API response for "${path}": expected "${key}" to be an array.`);
  }
  return items as T[];
}

export async function apiPost<T = Record<string, unknown>>(
  path: string,
  options?: {
    body?: Record<string, unknown>;
    params?: Record<string, string>;
    expected?: readonly number[];
    timeoutMs?: number;
  },
): Promise<T> {
  const client = new SynClient(
    options?.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : undefined,
  );
  const { status, data } = await safeRequest(() =>
    client.post<T>(path, options?.body, options?.params),
  );
  checkResponse(status, data, options?.expected ?? [200, 201]);
  return data;
}

export async function apiPut<T = Record<string, unknown>>(
  path: string,
  options?: {
    body?: Record<string, unknown>;
    expected?: readonly number[];
  },
): Promise<T> {
  const client = new SynClient();
  const { status, data } = await safeRequest(() =>
    client.put<T>(path, options?.body),
  );
  checkResponse(status, data, options?.expected ?? [200]);
  return data;
}

export async function apiPatch<T = Record<string, unknown>>(
  path: string,
  options?: {
    body?: Record<string, unknown>;
    expected?: readonly number[];
  },
): Promise<T> {
  const client = new SynClient();
  const { status, data } = await safeRequest(() =>
    client.patch<T>(path, options?.body),
  );
  checkResponse(status, data, options?.expected ?? [200]);
  return data;
}

export async function apiDelete<T = Record<string, unknown>>(
  path: string,
  options?: {
    expected?: readonly number[];
  },
): Promise<T> {
  const client = new SynClient();
  const { status, data } = await safeRequest(() => client.delete<T>(path));
  checkResponse(status, data, options?.expected ?? [200]);
  return data;
}

export function buildParams(
  params: Record<string, string | number | boolean | null | undefined>,
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) {
      result[key] = String(value);
    }
  }
  return result;
}
