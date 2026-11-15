export type Severity = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL" | "UNKNOWN";

export interface LogEvent {
  id: number;
  timestamp: string;
  severity: Severity;
  service: string;
  source: string;
  message: string;
}

export interface Metrics {
  total_events: number;
  error_rate: number;
  events_per_second: number;
  by_severity: Record<string, number>;
}

export interface TimelinePoint {
  bucket: string;
  total: number;
  errors: number;
  spike: boolean;
}

export interface AlertRule {
  id: number;
  name: string;
  threshold: number;
  window_minutes: number;
  enabled: boolean;
  created_at: string;
}

export interface TriggeredAlert {
  id: number;
  rule_id: number;
  rule_name: string;
  message: string;
  count: number;
  triggered_at: string;
}

export interface LogFilters {
  search: string;
  severity: string;
  service: string;
  range: string;
}

export interface Anomaly {
  bucket: string;
  metric: "errors" | "total";
  observed: number;
  expected: number;
  score: number;
  level: "medium" | "high";
}

export interface LogCluster {
  id: string;
  template: string;
  count: number;
  severity: Severity;
  services: string[];
  first_seen: string;
  last_seen: string;
  example: string;
}
