import type { AlertRule, LogEvent, LogFilters, Metrics, TimelinePoint, TriggeredAlert } from "./types";

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
  params.set("limit", "200");
  return params.toString();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const fetchLogs = (filters: LogFilters) =>
  request<LogEvent[]>(`/logs?${buildLogQuery(filters)}`);
export const fetchMetrics = () => request<Metrics>("/metrics");
export const fetchTimeline = () => request<TimelinePoint[]>("/timeline");
export const fetchServices = () => request<string[]>("/services");
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
