export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function extractErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.error === "string") return record.error;
    if (typeof record.detail === "string") return record.detail;
    if (Array.isArray(record.detail) && record.detail.length > 0) {
      const first = record.detail[0] as Record<string, unknown> | undefined;
      if (first && typeof first.msg === "string") return first.msg;
    }
  }
  return fallback;
}

/**
 * fetch() wrapped so a network failure (e.g. the agent process restarting mid-request
 * under `--reload` in dev) surfaces as a clear, distinguishable error instead of an
 * unhandled rejection or a misleading "not found" — a dropped connection isn't the same
 * thing as the server telling us the resource doesn't exist.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch {
    throw new ApiError("Could not reach the server — it may be restarting. Try again in a moment.");
  }
}

/** apiFetch + JSON parsing, throwing ApiError with the server's own message on non-2xx. */
export async function apiJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw new ApiError(extractErrorMessage(body, `Request failed (${response.status})`), response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
