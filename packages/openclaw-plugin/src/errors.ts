/** Format an error into an OpenClaw tool error response. */
export function formatError(error: unknown): { content: string; isError: true } {
  if (error instanceof ApiError) {
    return {
      content: `API error (${error.status}): ${error.message}`,
      isError: true,
    };
  }
  const message = error instanceof Error ? error.message : String(error);
  return { content: `Error: ${message}`, isError: true };
}

/** Structured API error with HTTP status. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
