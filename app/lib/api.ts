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
 * unhandled rejection or a misleading "not found" - a dropped connection isn't the same
 * thing as the server telling us the resource doesn't exist.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch {
    throw new ApiError("Could not reach the server - it may be restarting. Try again in a moment.");
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

/**
 * Consumes an SSE response body, invoking `onEvent` for each `data:` frame.
 *
 * The agent guarantees every stream ends with either `event: done` or an
 * `{type: "error"}` frame (agent/app/shared/sse.py) - but a dropped connection can still
 * end one mid-flight, so a stream that stops without either is reported as an error too.
 * Silently ending is the one outcome the UI must never show, because it is
 * indistinguishable from the assistant deciding to say nothing.
 */
export async function consumeSSE(
  response: Response,
  onEvent: (event: { type?: string; [key: string]: unknown }) => void,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new ApiError("The server sent an empty response.");
  const decoder = new TextDecoder();
  let buffer = "";
  let terminated = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Frames are separated by a blank line; a chunk can split one in half, so anything
    // after the last separator stays buffered until the rest arrives.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      if (frame.includes("event: done")) terminated = true;
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const payload = line.slice(6);
      if (!payload.trim() || payload === "{}") continue;
      let event: { type?: string };
      try {
        event = JSON.parse(payload);
      } catch {
        continue;
      }
      if (event.type === "error") {
        terminated = true;
        throw new ApiError(
          typeof (event as { message?: unknown }).message === "string"
            ? (event as { message: string }).message
            : "Something went wrong on the server.",
        );
      }
      onEvent(event);
    }
  }

  if (!terminated) {
    throw new ApiError("The connection dropped before the response finished.");
  }
}
