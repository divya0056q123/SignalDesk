import type {
  AlertRule, Anomaly, LogCluster, LogEvent, LogFilters, Metrics, TimelinePoint, TriggeredAlert,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

export function buildLogQuery(filters: LogFilters): string {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.service) params.set("service", filters.service);
  if (filters.range !== "all") {
    const minutes = filters.range === "15m" ? 15 : filters.range === "1h" ? 60 : 1440;
    params.set("start", new Date(Date.now() - minutes * 60_000).toISOString());
  }
  params.set("limit", "500");
  return params.toString();
}

const TOKEN_KEY = "signaldesk.token";
export const UNAUTHORIZED_EVENT = "signaldesk:unauthorized";

try { window.localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "same-origin" });
  if (
    response.status === 401
    && !["/auth/login", "/auth/register", "/auth/me", "/auth/status"].includes(path)
  ) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const fetchLogs = (filters: LogFilters) =>
  request<LogEvent[]>(`/logs?${buildLogQuery(filters)}`);
export const fetchMetrics = () => request<Metrics>("/metrics");
export const fetchTimeline = () => request<TimelinePoint[]>("/timeline");
export const fetchServices = () => request<string[]>("/services");
export const fetchAnomalies = () => request<Anomaly[]>("/anomalies?minutes=60");
export const fetchClusters = () => request<LogCluster[]>("/clusters?minutes=60&limit=8");
export const fetchRules = () => request<AlertRule[]>("/alerts/rules");
export const fetchAlerts = () => request<TriggeredAlert[]>("/alerts");
export const generateLogs = (count = 12) =>
  request<{ accepted: number }>("/logs/generate?count=" + count, { method: "POST" });
export const createRule = (body: { name: string; threshold: number; window_minutes: number }) =>
  request<AlertRule>("/alerts/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export async function uploadLogFile(file: File): Promise<{ accepted: number; rejected: number }> {
  const form = new FormData();
  form.append("file", file);
  return request("/logs/upload", { method: "POST", body: form });
}

export function websocketUrl(): string {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/logs`;
}

export interface AuthStatus {
  auth_enabled: boolean;
  needs_setup: boolean;
  registration_open: boolean;
  setup_token_required: boolean;
  email_verification_required: boolean;
}
export interface Session { username: string; email_verified: boolean }
export interface RegistrationResult {
  username: string;
  email_verification_sent: boolean;
}

export const fetchAuthStatus = () => request<AuthStatus>("/auth/status");
export const fetchCurrentUser = () =>
  request<{ username: string; email: string | null; email_verified: boolean }>("/auth/me");
export const logout = () => request<{ ok: boolean }>("/auth/logout", { method: "POST" });
const authBody = (username: string, password: string, setupToken?: string): RequestInit => {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (setupToken) headers["X-Setup-Token"] = setupToken;
  return { method: "POST", headers, body: JSON.stringify({ username, password }) };
};
export const login = (username: string, password: string) =>
  request<Session>("/auth/login", authBody(username, password));
export const register = (username: string, password: string, email: string, setupToken?: string) => {
  const init = authBody(username, password, setupToken);
  return request<RegistrationResult>("/auth/register", {
    ...init,
    body: JSON.stringify({ username, password, email }),
  });
};
const jsonPost = (path: string, body: Record<string, string>) =>
  request<{ ok?: boolean; message?: string; email_verification_sent?: boolean }>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const setAccountEmail = (email: string) => jsonPost("/auth/email", { email });
export const verifyEmail = (token: string) => jsonPost("/auth/verify-email", { token });
export const requestPasswordReset = (email: string) => jsonPost("/auth/password-reset/request", { email });
export const requestEmailVerification = (email: string) => jsonPost("/auth/verify-email/request", { email });
export const completePasswordReset = (token: string, password: string) =>
  jsonPost("/auth/password-reset/complete", { token, password });

export interface IngestKey {
  id: string;
  name: string;
  created_at: string;
}
export interface CreatedIngestKey {
  id: string;
  name: string;
  key: string;
}
export const fetchIngestKeys = () => request<IngestKey[]>("/ingest-keys");
export const createIngestKey = (name: string) =>
  request<CreatedIngestKey>("/ingest-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
export const revokeIngestKey = (id: string) =>
  request<void>(`/ingest-keys/${encodeURIComponent(id)}`, { method: "DELETE" });
