const API_PREFIX = import.meta.env.VITE_API_PREFIX ?? "/api";

type ApiRequestInit = Omit<RequestInit, "body"> & { body?: unknown };

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  const item = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

let csrfRequest: Promise<void> | null = null;

async function ensureCsrf() {
  if (readCookie("csrftoken")) return;
  csrfRequest ??= fetch(`${API_PREFIX}/auth/csrf/`, { credentials: "include" }).then((response) => {
    if (!response.ok) throw new ApiError("无法初始化安全令牌", response.status);
  });
  await csrfRequest;
}

function buildBody(body: unknown, headers: Headers) {
  if (body === undefined) return undefined;
  if (typeof body === "string") return body;
  if (body instanceof FormData) return body;
  headers.set("Content-Type", "application/json");
  return JSON.stringify(body);
}

async function request(path: string, options: ApiRequestInit = {}) {
  const method = (options.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) await ensureCsrf();
  const headers = new Headers(options.headers);
  const csrfToken = readCookie("csrftoken");
  if (csrfToken) headers.set("X-CSRFToken", csrfToken);
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    method,
    headers,
    credentials: "include",
    body: buildBody(options.body, headers),
  });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
    } catch {
      // Keep the HTTP status message when the server did not return JSON.
    }
    throw new ApiError(message, response.status);
  }
  return response;
}

export async function api<T>(path: string, options: ApiRequestInit = {}): Promise<T> {
  const response = await request(path, options);
  return response.json() as Promise<T>;
}

export async function apiStream(path: string, body: unknown): Promise<Response> {
  return request(path, { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
}
