let accessToken = "";
const pending = new Set<AbortController>();
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export function setToken(token: string) {
  accessToken = token;
  if (!token) {
    for (const controller of pending) controller.abort();
    pending.clear();
  }
}
export function getToken() {
  return accessToken;
}
async function request<T>(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  consume: (response: Response) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  pending.add(controller);
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    return await consume(response);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        init.method === "GET"
          ? "Request timed out or session ended. Try again when connected."
          : "Request interrupted. Check the saved record or job before retrying.",
      );
    throw new ApiError(
      "Network unavailable. Check the connection and try again.",
    );
  } finally {
    clearTimeout(timer);
    pending.delete(controller);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\"))
    throw new ApiError("Invalid API path");
  return request<T>(
    "/api/v1" + path,
    {
      method: method || (body ? "POST" : "GET"),
      headers: {
        Authorization: "Bearer " + accessToken,
        ...(body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
      },
      body:
        body instanceof FormData
          ? body
          : body
            ? JSON.stringify(body)
            : undefined,
    },
    body instanceof FormData ? 60000 : 20000,
    async (r) => {
      if (!r.ok) {
        const e = await r.json().catch(() => ({ detail: r.statusText }));
        throw new ApiError(
          typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
          r.status,
        );
      }
      return r.json();
    },
  );
}
export async function assetBlob(url: string): Promise<Blob> {
  if (!url.startsWith("/api/v1/") || url.includes("\\"))
    throw new ApiError("Download must be a project API resource");
  return request(
    url,
    { method: "GET", headers: { Authorization: "Bearer " + accessToken } },
    60000,
    async (r) => {
      if (!r.ok)
        throw new ApiError(
          "Source unavailable (" +
            r.status +
            "). The record remains accessible.",
          r.status,
        );
      return r.blob();
    },
  );
}
export async function download(url: string, name: string) {
  const blob = await assetBlob(url);
  const u = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
