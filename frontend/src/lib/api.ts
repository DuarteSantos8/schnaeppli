/** Thin fetch wrapper: same-origin cookies, CSRF header on writes, readable errors. */

export class ApiError extends Error {
  status: number;
  fields: { field: string; message: string }[];
  constructor(status: number, message: string, fields: { field: string; message: string }[] = []) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)schnaeppli_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", csrfToken());
  let res: Response;
  try {
    res = await fetch(path, { ...init, method, headers, body, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "You're offline or the server can't be reached.");
  }
  if (res.status === 204) return undefined as T;
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized && !path.startsWith("/api/auth/login")) onUnauthorized();
    const msg =
      (data && typeof data.detail === "string" && data.detail) ||
      (res.status >= 500 ? "Something went wrong on our side." : `Request failed (${res.status}).`);
    throw new ApiError(res.status, msg, data?.errors || []);
  }
  return data as T;
}

export const get = <T,>(p: string) => api<T>(p);
export const post = <T,>(p: string, json?: unknown) => api<T>(p, { method: "POST", json: json ?? {} });
export const patch = <T,>(p: string, json: unknown) => api<T>(p, { method: "PATCH", json });
export const put = <T,>(p: string, json: unknown) => api<T>(p, { method: "PUT", json });
export const del = <T,>(p: string, json?: unknown) => api<T>(p, { method: "DELETE", json });

/** Listing photos arrive as signed same-origin proxy URLs; only the width is chosen here. */
export function img(url: string | null | undefined, w = 640): string | undefined {
  if (!url || !url.startsWith("/api/img")) return undefined;
  return `${url}&w=${w}`;
}
