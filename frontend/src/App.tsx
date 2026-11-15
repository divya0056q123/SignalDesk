import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, Bell, Check, ChevronDown, CircleHelp,
  Clock3, Command, Copy, FileUp, Filter, KeyRound, ListFilter,
  LoaderCircle, MoreHorizontal, Plus, Radio, Search, ShieldAlert, Signal, Sparkles,
  Share2, Terminal, Trash2, Zap,
} from "lucide-react";
import {
  createIngestKey, createRule, fetchAlerts, fetchAnomalies, fetchClusters, fetchIngestKeys,
  fetchLogs, fetchMetrics, fetchRules, fetchServices, fetchTimeline, generateLogs,
  revokeIngestKey, uploadLogFile, websocketUrl,
} from "./api";
import type { CreatedIngestKey, IngestKey } from "./api";
import type {
  AlertRule, Anomaly, LogCluster, LogEvent, LogFilters, Metrics, TimelinePoint, TriggeredAlert,
} from "./types";

const emptyMetrics: Metrics = {
  total_events: 0, error_rate: 0, events_per_second: 0, by_severity: {},
};
const initialFilters: LogFilters = { search: "", severity: "", service: "", range: "1h" };
const logRanges = ["15m", "1h", "24h", "all"];
const logSeverities = ["", "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "UNKNOWN"];

interface SavedLogSearch {
  id: string;
  name: string;
  filters: LogFilters;
}

function filtersFromUrl(): LogFilters {
  const params = new URLSearchParams(window.location.search);
  const range = params.get("range") ?? "";
  const severity = params.get("severity") ?? "";
  return {
    search: (params.get("q") ?? "").slice(0, 200),
    severity: logSeverities.includes(severity) ? severity : "",
    service: (params.get("service") ?? "").slice(0, 100),
    range: logRanges.includes(range) ? range : initialFilters.range,
  };
}

function urlForFilters(filters: LogFilters): string {
  const url = new URL(window.location.href);
  const values: Record<string, string> = {
    q: filters.search.trim(),
    severity: filters.severity,
    service: filters.service,
    range: filters.range === initialFilters.range ? "" : filters.range,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  return url.toString();
}

function parseSavedSearches(value: string | null): SavedLogSearch[] {
  if (!value) return [];
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed)) throw new Error("Saved searches have an invalid format.");
  return parsed.map((item: unknown) => {
    if (!item || typeof item !== "object") throw new Error("A saved search is invalid.");
    const record = item as Record<string, unknown>;
    const filters = record.filters;
    if (
      typeof record.id !== "string" || typeof record.name !== "string" || !record.name.trim()
      || !filters || typeof filters !== "object"
    ) throw new Error("A saved search is invalid.");
    const filterValues = filters as Record<string, unknown>;
    if (
      typeof filterValues.search !== "string" || typeof filterValues.severity !== "string"
      || typeof filterValues.service !== "string" || typeof filterValues.range !== "string"
      || !logSeverities.includes(filterValues.severity) || !logRanges.includes(filterValues.range)
    ) throw new Error("A saved search contains invalid filters.");
    return {
      id: record.id,
      name: record.name.slice(0, 80),
      filters: {
        search: filterValues.search.slice(0, 200),
        severity: filterValues.severity,
        service: filterValues.service.slice(0, 100),
        range: filterValues.range,
      },
    };
  });
}

function sectionFromHash(): "overview" | "logs" | "alerts" {
  const section = window.location.hash.slice(1);
  return section === "logs" || section === "alerts" ? section : "overview";
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function SeverityPill({ severity }: { severity: string }) {
  return <span className={`severity-pill severity-${severity.toLowerCase()}`}><i />{severity}</span>;
}

function MetricCard({ label, value, detail, icon: Icon, tone, trend }: {
  label: string; value: string; detail: string; icon: string; tone: string; trend?: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><img src={Icon} alt="" /></span></div>
      <div className="metric-value">{value}</div>
      {trend && <span className={`metric-trend ${trend === "Healthy" || trend === "Live" ? "trend-good" : trend === "Elevated" ? "trend-warning" : ""}`}><i />{trend}</span>}
      <div className="metric-detail"><span className="detail-dot" />{detail}</div>
    </article>
  );
}

function EventTimeline({ points }: { points: TimelinePoint[] }) {
  const width = 760;
  const left = 31;
  const right = 8;
  const top = 8;
  const plotHeight = 116;
  const plotWidth = width - left - right;
  const maximum = Math.max(1, ...points.map((point) => point.total));
  const step = plotWidth / Math.max(1, points.length);
  const labelIndexes = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  return (
    <svg className="timeline-svg" viewBox={`0 0 ${width} 152`} role="img" aria-label="Log events and error volume over time">
      {[0, 0.5, 1].map((ratio) => {
        const y = top + plotHeight * (1 - ratio);
        return <g key={ratio}>
          <line x1={left} y1={y} x2={width - right} y2={y} stroke="#dce5f1" strokeDasharray="3 5" />
          <text x={left - 7} y={y + 3} textAnchor="end" fill="#8291a6" fontSize="9">{Math.round(maximum * ratio)}</text>
        </g>;
      })}
      {points.map((point, index) => {
        const x = left + index * step;
        const totalHeight = (point.total / maximum) * plotHeight;
        const errorHeight = (point.errors / maximum) * plotHeight;
        return <g key={point.bucket}>
          <title>{`${new Date(point.bucket).toLocaleString()}: ${point.total} events, ${point.errors} errors${point.spike ? " · error spike" : ""}`}</title>
          <rect x={x + step * 0.14} y={top + plotHeight - totalHeight} width={Math.max(1, step * 0.56)} height={totalHeight} rx="2" fill={point.spike ? "#e45b6c" : "#3978df"} fillOpacity={point.spike ? 1 : 0.82} />
          {point.errors > 0 && <rect x={x + step * 0.72} y={top + plotHeight - errorHeight} width={Math.max(1, step * 0.2)} height={errorHeight} rx="1" fill="#ef9b47" />}
        </g>;
      })}
      {labelIndexes.map((index) => points[index] && <text key={index} x={left + index * step + step / 2} y="146" textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"} fill="#747f8d" fontSize="9">
        {new Date(points[index].bucket).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
      </text>)}
    </svg>
  );
}

function App({ username, onSignOut }: { username?: string; onSignOut?: () => void }) {
  const workspaceName = username ? `${username}'s workspace` : "Local workspace";
  const [filters, setFilters] = useState(filtersFromUrl);
  const [savedSearches, setSavedSearches] = useState<SavedLogSearch[]>([]);
  const [savedSearchesLoaded, setSavedSearchesLoaded] = useState(false);
  const [selectedSavedSearch, setSelectedSavedSearch] = useState("");
  const [showSaveSearchForm, setShowSaveSearchForm] = useState(false);
  const [savedSearchName, setSavedSearchName] = useState("");
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [metrics, setMetrics] = useState(emptyMetrics);
  const [timeline, setTimeline] = useState<TimelinePoint[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [alerts, setAlerts] = useState<TriggeredAlert[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [clusters, setClusters] = useState<LogCluster[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [openPanel, setOpenPanel] = useState<"workspace" | "notifications" | "profile" | null>(null);
  const [activeSection, setActiveSection] = useState<"overview" | "logs" | "alerts">(sectionFromHash);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [ruleName, setRuleName] = useState("");
  const [threshold, setThreshold] = useState("5");
  const [windowMinutes, setWindowMinutes] = useState("5");
  const [showKeyManager, setShowKeyManager] = useState(false);
  const [ingestKeys, setIngestKeys] = useState<IngestKey[]>([]);
  const [keyName, setKeyName] = useState("");
  const [createdIngestKey, setCreatedIngestKey] = useState<CreatedIngestKey | null>(null);
  const [keyManagerBusy, setKeyManagerBusy] = useState(false);
  const [keyManagerError, setKeyManagerError] = useState("");
  const [keyListLoaded, setKeyListLoaded] = useState(false);
  const savedSearchesKey = `signaldesk:saved-searches:${encodeURIComponent(username || "local")}`;
  const fileRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const workspaceMenuRef = useRef<HTMLDivElement>(null);
  const topMenusRef = useRef<HTMLDivElement>(null);
  const filtersRef = useRef(filters);
  const refreshTimer = useRef<number | undefined>(undefined);
  const streamRefreshTimer = useRef<number | undefined>(undefined);
  filtersRef.current = filters;

  useEffect(() => {
    try {
      setSavedSearches(parseSavedSearches(window.localStorage.getItem(savedSearchesKey)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Saved searches could not be loaded.");
    } finally {
      setSavedSearchesLoaded(true);
    }
  }, [savedSearchesKey]);

  useEffect(() => {
    if (!savedSearchesLoaded) return;
    try {
      window.localStorage.setItem(savedSearchesKey, JSON.stringify(savedSearches));
    } catch {
      setError("Saved searches could not be saved in this browser.");
    }
  }, [savedSearches, savedSearchesKey, savedSearchesLoaded]);

  useEffect(() => {
    const nextUrl = urlForFilters(filters);
    const currentUrl = `${window.location.origin}${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (nextUrl !== currentUrl) window.history.replaceState(window.history.state, "", nextUrl);
  }, [filters]);

  function navigateTo(section: "overview" | "logs" | "alerts") {
    if (window.location.hash !== `#${section}`) window.location.hash = section;
    setActiveSection(section);
    setOpenPanel(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function onSaveSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = savedSearchName.trim();
    if (!name) return;
    const savedSearch: SavedLogSearch = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: name.slice(0, 80),
      filters: { ...filters },
    };
    setSavedSearches((current) => [...current, savedSearch]);
    setSelectedSavedSearch(savedSearch.id);
    setSavedSearchName("");
    setShowSaveSearchForm(false);
    setNotice(`Saved search "${savedSearch.name}".`);
    setError("");
  }

  function applySavedSearch(id: string) {
    setSelectedSavedSearch(id);
    const savedSearch = savedSearches.find((item) => item.id === id);
    if (savedSearch) setFilters({ ...savedSearch.filters });
  }

  function deleteSavedSearch() {
    if (!selectedSavedSearch) return;
    setSavedSearches((current) => current.filter((item) => item.id !== selectedSavedSearch));
    setSelectedSavedSearch("");
  }

  async function shareCurrentFilters() {
    try {
      const shareUrl = new URL(urlForFilters(filters));
      shareUrl.hash = "#logs";
      await navigator.clipboard.writeText(shareUrl.toString());
      setNotice("Shareable log search URL copied.");
      setError("");
    } catch {
      setError("Could not copy the search URL. You can copy it from the browser address bar.");
    }
  }

  function exportLogs(format: "csv" | "json") {
    if (!logs.length) return;
    const content = format === "json"
      ? JSON.stringify(logs, null, 2)
      : [
        ["timestamp", "severity", "service", "source", "message"],
        ...logs.map((log) => [log.timestamp, log.severity, log.service, log.source, log.message]),
      ].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const blob = new Blob([content], {
      type: format === "json" ? "application/json;charset=utf-8" : "text/csv;charset=utf-8",
    });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `signaldesk-logs-${new Date().toISOString().replace(/:/g, "-")}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    setNotice(`Exported ${logs.length} filtered events as ${format.toUpperCase()}.`);
    setError("");
  }

  const refreshDashboard = useCallback(async () => {
    try {
      const [
        nextLogs, nextMetrics, nextTimeline, nextRules, nextAlerts, nextServices, nextAnomalies, nextClusters,
      ] = await Promise.all([
        fetchLogs(filters), fetchMetrics(), fetchTimeline(), fetchRules(), fetchAlerts(), fetchServices(),
        fetchAnomalies(), fetchClusters(),
      ]);
      setLogs(nextLogs);
      setMetrics(nextMetrics);
      setTimeline(nextTimeline);
      setRules(nextRules);
      setAlerts(nextAlerts);
      setServices(nextServices);
      setAnomalies(nextAnomalies);
      setClusters(nextClusters);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to reach the log service.");
    }
  }, [filters]);

  useEffect(() => {
    window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => { void refreshDashboard(); }, 180);
    return () => window.clearTimeout(refreshTimer.current);
  }, [refreshDashboard]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (activeSection !== "logs") navigateTo("logs");
        window.setTimeout(() => searchRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [activeSection]);

  useEffect(() => {
    const updateSection = () => {
      const section = window.location.hash.slice(1);
      setActiveSection(section === "logs" || section === "alerts" ? section : "overview");
      window.scrollTo({ top: 0, behavior: "auto" });
    };
    const closeOnOutsideClick = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (!workspaceMenuRef.current?.contains(target) && !topMenusRef.current?.contains(target)) {
        setOpenPanel(null);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenPanel(null);
    };
    updateSection();
    window.addEventListener("hashchange", updateSection);
    document.addEventListener("pointerdown", closeOnOutsideClick);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("hashchange", updateSection);
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void Promise.all([fetchMetrics(), fetchTimeline(), fetchAlerts(), fetchAnomalies(), fetchClusters()])
        .then(([nextMetrics, nextTimeline, nextAlerts, nextAnomalies, nextClusters]) => {
          setMetrics(nextMetrics); setTimeline(nextTimeline); setAlerts(nextAlerts);
          setAnomalies(nextAnomalies); setClusters(nextClusters);
        })
        .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Refresh failed."));
    }, 10_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    let connectTimer: number | undefined;
    let stopped = false;
    const connect = () => {
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => {
        if (stopped) {
          socket?.close();
          return;
        }
        setConnected(true);
      };
      socket.onclose = () => {
        setConnected(false);
        if (!stopped) reconnectTimer = window.setTimeout(connect, 1800);
      };
      socket.onerror = () => socket?.close();
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as { type: string; data: LogEvent | TriggeredAlert | Anomaly };
          if (event.type === "log") {
            const log = event.data as LogEvent;
            if (log.id) {
              window.clearTimeout(streamRefreshTimer.current);
              streamRefreshTimer.current = window.setTimeout(() => {
                void Promise.all([
                  fetchLogs(filtersRef.current), fetchMetrics(), fetchTimeline(), fetchServices(),
                ]).then(([nextLogs, nextMetrics, nextTimeline, nextServices]) => {
                  setLogs(nextLogs); setMetrics(nextMetrics); setTimeline(nextTimeline); setServices(nextServices);
                }).catch((cause: unknown) => {
                  setError(cause instanceof Error ? cause.message : "Unable to refresh live data.");
                });
              }, 120);
            }
          } else if (event.type === "anomaly") {
            const anomaly = event.data as Anomaly;
            setAnomalies((current) => [anomaly, ...current.filter((item) => !(item.bucket === anomaly.bucket && item.metric === anomaly.metric))].slice(0, 20));
            setNotice(`Anomaly detected: ${anomaly.observed} ${anomaly.metric === "errors" ? "errors" : "events"}/min (expected ~${anomaly.expected})`);
          } else if (event.type === "alert") {
            const alert = event.data as TriggeredAlert;
            setAlerts((current) => [alert, ...current.filter((item) => item.id !== alert.id)].slice(0, 50));
          }
        } catch {
          setError("The live stream sent an unreadable event.");
        }
      };
    };
    connectTimer = window.setTimeout(connect, 0);
    return () => {
      stopped = true;
      window.clearTimeout(connectTimer);
      window.clearTimeout(reconnectTimer);
      window.clearTimeout(streamRefreshTimer.current);
      if (socket?.readyState === WebSocket.OPEN) socket.close();
    };
  }, []);

  const severityCounts = useMemo(() => {
    const keys = ["ERROR", "WARNING", "INFO", "DEBUG", "UNKNOWN", "CRITICAL"];
    return keys.map((key) => ({ name: key, count: metrics.by_severity[key] ?? 0 }));
  }, [metrics.by_severity]);

  async function runGenerator() {
    setBusy(true);
    setNotice("");
    try {
      const result = await generateLogs();
      setNotice(`${result.accepted} sample events added to the stream.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not generate sample logs.");
    } finally {
      setBusy(false);
    }
  }

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setNotice("");
    try {
      const result = await uploadLogFile(file);
      setNotice(`Imported ${result.accepted} events${result.rejected ? ` · skipped ${result.rejected} oversized lines` : ""}.`);
      await refreshDashboard();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed.");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function onCreateRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await createRule({ name: ruleName.trim(), threshold: Number(threshold), window_minutes: Number(windowMinutes) });
      setRuleName("");
      setShowRuleForm(false);
      setNotice("Alert rule created.");
      await refreshDashboard();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create alert rule.");
    }
  }

  async function openKeyManager() {
    setOpenPanel(null);
    setShowKeyManager(true);
    setKeyManagerError("");
    setCreatedIngestKey(null);
    setIngestKeys([]);
    setKeyListLoaded(false);
    try {
      setIngestKeys(await fetchIngestKeys());
      setKeyListLoaded(true);
    } catch (cause) {
      setKeyManagerError(cause instanceof Error ? cause.message : "Could not load ingestion keys.");
    }
  }

  function closeKeyManager() {
    setShowKeyManager(false);
    setCreatedIngestKey(null);
    setKeyName("");
    setKeyManagerError("");
  }

  async function onCreateIngestKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setKeyManagerBusy(true);
    setKeyManagerError("");
    try {
      const created = await createIngestKey(keyName.trim());
      setCreatedIngestKey(created);
      setKeyName("");
      try {
        setIngestKeys(await fetchIngestKeys());
        setKeyListLoaded(true);
      } catch {
        setKeyManagerError("The key was created, but the active-key list could not be refreshed.");
      }
    } catch (cause) {
      setKeyManagerError(cause instanceof Error ? cause.message : "Could not create ingestion key.");
    } finally {
      setKeyManagerBusy(false);
    }
  }

  async function onRevokeIngestKey(key: IngestKey) {
    if (!window.confirm(`Revoke "${key.name}"? Applications using it will no longer be able to send logs.`)) return;
    setKeyManagerBusy(true);
    setKeyManagerError("");
    try {
      await revokeIngestKey(key.id);
      setIngestKeys((current) => current.filter((item) => item.id !== key.id));
      setNotice(`Ingestion key "${key.name}" revoked.`);
    } catch (cause) {
      setKeyManagerError(cause instanceof Error ? cause.message : "Could not revoke ingestion key.");
    } finally {
      setKeyManagerBusy(false);
    }
  }

  async function copyIngestKey() {
    if (!createdIngestKey) return;
    try {
      await navigator.clipboard.writeText(createdIngestKey.key);
      setNotice("Ingestion key copied to clipboard.");
    } catch (cause) {
      setKeyManagerError(cause instanceof Error ? cause.message : "Could not copy the key.");
    }
  }

  const maxSeverity = Math.max(1, ...severityCounts.map((item) => item.count));
  const hasTimelineData = timeline.some((point) => point.total > 0);
  const pageHeading = activeSection === "logs"
    ? { eyebrow: "LOG EXPLORER", title: "Explore your logs", description: "Search, filter, and inspect events across your services." }
    : activeSection === "alerts"
      ? { eyebrow: "ALERT MANAGEMENT", title: "Manage alerts", description: "Review triggered alerts and manage the rules that watch your services." }
      : {
        eyebrow: "SYSTEM OVERVIEW",
        title: `Good afternoon${username ? `, ${username}` : ""}`,
        description: hasTimelineData
          ? "Your services are reporting. Here’s the latest activity across your workspace."
          : "Bring your application logs together and get a clear view of service health.",
      };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={(event) => { event.preventDefault(); navigateTo("overview"); }} aria-label="Real-Time Log Analyzer home">
          <span className="brand-mark"><img src="/icons/brand-mark.svg" alt="" /></span>
          <span className="brand-name">Real-Time<span>Log Analyzer</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <div className="workspace-menu-wrap" ref={workspaceMenuRef}>
          <button className="workspace-switch" aria-expanded={openPanel === "workspace"} aria-controls="workspace-menu" onClick={() => setOpenPanel(openPanel === "workspace" ? null : "workspace")}>
            <span className="workspace-avatar">{(username?.[0] ?? "L").toUpperCase()}</span><span className="workspace-copy"><b>{workspaceName}</b><small>Private workspace</small></span>
            <ChevronDown size={15} />
          </button>
          {openPanel === "workspace" && <div className="workspace-popover" id="workspace-menu" role="dialog" aria-label="Workspace details">
            <b>{workspaceName}</b>
            <p>{username ? "Your logs, alerts, and services are private to this account." : "This local workspace is available to anyone using this installation."}</p>
            <span><Signal size={12} /> Data stored locally</span>
          </div>}
        </div>
        <div className="nav-label">OBSERVABILITY</div>
        <nav className="side-nav" aria-label="Main navigation">
          <a className={`nav-link ${activeSection === "overview" ? "selected" : ""}`} href="#overview" aria-current={activeSection === "overview" ? "page" : undefined} onClick={(event) => { event.preventDefault(); navigateTo("overview"); }}><img className="nav-image-icon" src="/icons/overview.svg" alt="" />Overview{activeSection === "overview" && <span className="nav-active" />}</a>
          <a className={`nav-link ${activeSection === "logs" ? "selected" : ""}`} href="#logs" aria-current={activeSection === "logs" ? "page" : undefined} onClick={(event) => { event.preventDefault(); navigateTo("logs"); }}><img className="nav-image-icon" src="/icons/logs.svg" alt="" />Log explorer{activeSection === "logs" && <span className="nav-active" />}</a>
          <a className={`nav-link ${activeSection === "alerts" ? "selected" : ""}`} href="#alerts" aria-current={activeSection === "alerts" ? "page" : undefined} onClick={(event) => { event.preventDefault(); navigateTo("alerts"); }}><img className="nav-image-icon" src="/icons/alerts.svg" alt="" />Alerts{alerts.length > 0 && <span className="nav-count">{alerts.length}</span>}{activeSection === "alerts" && <span className="nav-active" />}</a>
        </nav>
        <div className="nav-label sources-label">DETECTED SERVICES</div>
        <div className="source-list" aria-label="Detected services">
          {services.slice(0, 5).map((service) => <div className="source-item" key={service}><img src="/icons/services.svg" alt="" />{service}<span className="source-live">detected</span></div>)}
          {services.length === 0 && <div className="source-empty"><span>Services are identified from incoming logs.</span><a href="#logs" onClick={(event) => { event.preventDefault(); navigateTo("logs"); }}>Import logs to discover services<ArrowRight size={12} /></a></div>}
        </div>
        <div className="sidebar-bottom">
          <div className="plan-card"><span className="plan-icon"><Sparkles size={15} /></span><b>Make it yours</b><p>Explore your logs and add application events to this workspace.</p><a href="#logs" onClick={(event) => { event.preventDefault(); navigateTo("logs"); }}>Open log explorer <ArrowDownToLine size={13} /></a></div>
          <a className="nav-link help-link" href="https://fastapi.tiangolo.com/" target="_blank" rel="noreferrer"><CircleHelp size={16} />Documentation</a>
          <div className="user-profile"><span className="user-avatar">{(username ?? "RT").slice(0, 2).toUpperCase()}</span><span><b>{username ?? "Guest"}</b><small>Log Analyzer account</small></span></div>
        </div>
      </aside>

      <main className="main-area" id="overview">
        <header className="topbar">
          <div className="breadcrumbs"><a href="#overview" onClick={(event) => { event.preventDefault(); navigateTo("overview"); }}>Workspace</a><span className="crumb-divider">/</span><span className="breadcrumb-current">{activeSection === "logs" ? "Log explorer" : activeSection === "alerts" ? "Alerts" : "Overview"}</span></div>
          <div className="top-actions" ref={topMenusRef}>
            <div className={`connection-pill ${connected ? "is-connected" : ""}`}><span />{connected ? "Live connected" : "Connecting"}</div>
            <div className="popover-anchor">
              <button className="icon-button" aria-label="Notifications" aria-expanded={openPanel === "notifications"} aria-controls="notifications-menu" onClick={() => setOpenPanel(openPanel === "notifications" ? null : "notifications")}><Bell size={17} />{alerts.length > 0 && <i />}</button>
              {openPanel === "notifications" && <div className="header-popover notification-popover" id="notifications-menu" role="dialog" aria-label="Notifications">
                <div className="popover-heading"><b>Notifications</b><span>{alerts.length}</span></div>
                {alerts.length ? <div className="notification-list">{alerts.slice(0, 5).map((alert) => <div className="notification-item" key={alert.id}><b>{alert.rule_name}</b><p>{alert.message}</p><small>{formatDate(alert.triggered_at)}</small></div>)}</div> : <p className="popover-empty">No recent notifications. Triggered alerts will appear here.</p>}
                <a className="popover-link" href="#alerts" onClick={() => setOpenPanel(null)}>View alert activity</a>
              </div>}
            </div>
            <div className="popover-anchor">
              <button className="top-avatar" title={username ?? "Account"} aria-label="Account menu" aria-expanded={openPanel === "profile"} aria-controls="profile-menu" onClick={() => setOpenPanel(openPanel === "profile" ? null : "profile")}>{(username ?? "DS").slice(0, 2).toUpperCase()}</button>
              {openPanel === "profile" && <div className="header-popover profile-popover" id="profile-menu" role="dialog" aria-label="Account">
                <div className="profile-summary"><span className="user-avatar">{(username ?? "RT").slice(0, 2).toUpperCase()}</span><span><b>{username ?? "Guest"}</b><small>Log Analyzer account</small></span></div>
                {onSignOut && <button className="profile-action" onClick={() => void openKeyManager()}><KeyRound size={14} />Manage ingestion keys</button>}
                {onSignOut && <button className="profile-signout" onClick={onSignOut}>Sign out</button>}
              </div>}
            </div>
            {onSignOut && <button className="button button-secondary sign-out" onClick={onSignOut}>Sign out</button>}
          </div>
        </header>

        <div className="content-wrap">
          <section className="page-heading hero-panel">
            <div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line" />{pageHeading.eyebrow}</div><h1>{pageHeading.title}{activeSection === "overview" && <span className="wave"> ✦</span>}</h1>
              <p>{pageHeading.description}</p>
              <div className="hero-status"><span className={`hero-status-dot ${connected ? "is-live" : ""}`} />{connected ? "Live monitoring" : "Connecting to live stream"}<span className="hero-status-divider" />{metrics.total_events.toLocaleString()} events<span className="hero-status-divider" />{services.length} active {services.length === 1 ? "service" : "services"}</div>
              {activeSection === "overview" && <div className="hero-cta-row"><button className="button button-primary hero-import" onClick={() => navigateTo("logs")}><FileUp size={15} />Open log explorer</button><button className="button button-secondary" onClick={() => setShowRuleForm(true)}><Bell size={15} />Create alert</button></div>}
            </div>
            {activeSection === "overview" && <div className="hero-visual"><img src="/illustrations/log-workspace.svg" alt="Log management dashboard preview" /></div>}
            <div className="heading-actions">
              {activeSection === "logs" && <>
                <button className="button button-primary hero-import" onClick={() => fileRef.current?.click()} disabled={busy}><FileUp size={15} />Import logs</button>
                <input ref={fileRef} type="file" accept=".log,.txt,text/plain" hidden onChange={(event) => void onFileChange(event)} />
                <button className="button button-secondary" onClick={() => void runGenerator()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Zap size={15} />}Generate sample</button>
              </>}
              {activeSection === "alerts" && <button className="button button-primary" onClick={() => setShowRuleForm(true)}><Plus size={15} />Create alert rule</button>}
            </div>
          </section>

          {(error || notice) && <div className={`toast ${error ? "toast-error" : ""}`} role="status"><span>{error || notice}</span><button aria-label="Dismiss message" onClick={() => { setError(""); setNotice(""); }}>×</button></div>}

          {activeSection === "overview" && <section className="metric-grid" aria-label="Live metrics">
            <MetricCard label="Total events" value={metrics.total_events.toLocaleString()} detail="All time · across your services" icon="/icons/events.svg" tone="violet" trend={hasTimelineData ? "Live" : "Awaiting logs"} />
            <MetricCard label="Error rate" value={`${(metrics.error_rate * 100).toFixed(1)}%`} detail="Errors + critical events" icon="/icons/errors.svg" tone="rose" trend={metrics.error_rate > 0.1 ? "Elevated" : hasTimelineData ? "Healthy" : "No data"} />
            <MetricCard label="Events / second" value={metrics.events_per_second.toFixed(2)} detail="Rolling 60-second window" icon="/icons/throughput.svg" tone="blue" trend={connected ? "Live" : "Connecting"} />
            <MetricCard label="Active services" value={String(services.length).padStart(2, "0")} detail="Reporting in this workspace" icon="/icons/services.svg" tone="mint" trend={services.length ? "Healthy" : "No services yet"} />
          </section>}

          {activeSection === "overview" && <section className="visual-grid">
            <article className="panel chart-panel">
              <div className="panel-heading"><div><div className="panel-title">Event volume</div><div className="panel-subtitle">Log activity over the last 60 minutes</div></div><div className="chart-legend"><span><i className="legend-events" />Events</span><span><i className="legend-errors" />Errors</span><button className="select-small"><Clock3 size={13} />Last hour<ChevronDown size={13} /></button></div></div>
              <div className={`chart-wrap ${!hasTimelineData ? "is-empty" : ""}`}>
                {hasTimelineData ? <EventTimeline points={timeline} /> : <div className="chart-empty">
                  <span className="chart-empty-icon"><Activity size={22} /></span>
                  <b>Your event timeline starts here</b>
                  <span>Import a log file to see volume and error trends across your services.</span>
                  <button className="button button-primary" onClick={() => navigateTo("logs")}>Open log explorer<ArrowRight size={14} /></button>
                </div>}
              </div>
              <div className="chart-footnote"><span className="spike-indicator" />Spikes are highlighted when error volume is unusually high</div>
            </article>
            <article className="panel severity-panel">
              <div className="panel-heading"><div><div className="panel-title">Severity breakdown</div><div className="panel-subtitle">Distribution across all events</div></div><button className="icon-button subtle" aria-label="More severity options"><MoreHorizontal size={18} /></button></div>
              <div className="severity-total"><b>{metrics.total_events.toLocaleString()}</b><span>total events</span></div>
              <div className="severity-bars">{severityCounts.filter((item) => item.count > 0 || ["ERROR", "WARNING", "INFO", "DEBUG"].includes(item.name)).map((item) => (
                <div className="severity-row" key={item.name}><span className={`severity-label color-${item.name.toLowerCase()}`}>{item.name}</span><div className="severity-track"><div className={`severity-fill fill-${item.name.toLowerCase()}`} style={{ width: `${(item.count / maxSeverity) * 100}%` }} /></div><span className="severity-count">{item.count}</span></div>
              ))}</div>
              <div className="severity-foot"><span className="live-dot" />Updated in real time</div>
            </article>
          </section>}

          {(activeSection === "overview" || activeSection === "logs") && <section className={`lower-grid ${activeSection === "logs" ? "log-explorer-grid" : ""}`}>
            <article className={`panel log-panel ${activeSection === "overview" ? "log-summary-panel" : "log-detail-panel"}`}>
              <div className="panel-heading log-heading"><div><div className="panel-title">{activeSection === "overview" ? "Recent log activity" : "Live log stream"} {activeSection === "logs" && <span className="live-tag"><i />LIVE</span>}</div><div className="panel-subtitle">{activeSection === "overview" ? "Latest events from across your services" : "Search, filter, and inspect incoming events"}</div></div>
                {activeSection === "overview"
                  ? <button className="text-link" onClick={() => navigateTo("logs")}>Open log explorer<ArrowRight size={13} /></button>
                  : <button className="icon-button subtle" aria-label="Log table options"><MoreHorizontal size={18} /></button>}
              </div>
              {activeSection === "logs" && <>
              <div className="filter-toolbar">
                <label className="search-input"><Search size={15} /><input ref={searchRef} aria-label="Search logs" placeholder="Search messages, services…" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} /><kbd>⌘ K</kbd></label>
                <label className="filter-select"><Filter size={13} /><select aria-label="Filter by severity" value={filters.severity} onChange={(event) => setFilters({ ...filters, severity: event.target.value })}><option value="">All levels</option><option>CRITICAL</option><option>ERROR</option><option>WARNING</option><option>INFO</option><option>DEBUG</option><option>UNKNOWN</option></select><ChevronDown size={13} /></label>
                <label className="filter-select"><ListFilter size={13} /><select aria-label="Filter by service" value={filters.service} onChange={(event) => setFilters({ ...filters, service: event.target.value })}><option value="">All services</option>{services.map((service) => <option key={service}>{service}</option>)}</select><ChevronDown size={13} /></label>
                <label className="filter-select range-select"><Clock3 size={13} /><select aria-label="Filter by time range" value={filters.range} onChange={(event) => setFilters({ ...filters, range: event.target.value })}><option value="15m">Last 15 min</option><option value="1h">Last hour</option><option value="24h">Last 24 hours</option><option value="all">All time</option></select><ChevronDown size={13} /></label>
              </div>
              <div className="saved-search-toolbar">
                <label className="saved-search-select">Saved searches
                  <select aria-label="Saved searches" value={selectedSavedSearch} onChange={(event) => applySavedSearch(event.target.value)}>
                    <option value="">Choose a saved search</option>
                    {savedSearches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                <div className="saved-search-actions">
                  <button className="button button-secondary" type="button" onClick={() => setShowSaveSearchForm(true)}><Plus size={13} />Save search</button>
                  <button className="button button-secondary" type="button" onClick={() => void shareCurrentFilters()}><Share2 size={13} />Share filters</button>
                  <button className="button button-secondary" type="button" disabled={!logs.length} onClick={() => exportLogs("csv")}><ArrowDownToLine size={13} />Export CSV</button>
                  <button className="button button-secondary" type="button" disabled={!logs.length} onClick={() => exportLogs("json")}><ArrowDownToLine size={13} />Export JSON</button>
                  <button className="button button-secondary saved-search-delete" type="button" aria-label="Delete saved search" disabled={!selectedSavedSearch} onClick={deleteSavedSearch}><Trash2 size={13} /></button>
                </div>
              </div>
              </>}
              <div className="table-scroll">
                <table className="log-table"><thead><tr><th>TIME</th><th>LEVEL</th><th>SERVICE</th><th>MESSAGE</th></tr></thead>
                  <tbody>{(activeSection === "overview" ? logs.slice(0, 5) : logs).map((log) => <tr key={log.id}><td className="time-cell">{formatTime(log.timestamp)}</td><td><SeverityPill severity={log.severity} /></td><td><span className="service-name">{log.service}</span></td><td className="message-cell" title={log.message}>{log.message}</td></tr>)}
                    {!logs.length && <tr><td colSpan={4} className="empty-row">{activeSection === "overview" ? "No logs yet. Open Log Explorer to import or generate events." : "No events match your filters."}</td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="table-footer"><span>Showing <b>{activeSection === "overview" ? Math.min(logs.length, 5) : logs.length}</b> {activeSection === "overview" ? "latest" : "recent"} events</span><span className="stream-status"><Radio size={12} />Stream {connected ? "active" : "reconnecting"}</span></div>
            </article>

          </section>}
          {(activeSection === "overview" || activeSection === "alerts") && <section className={`insights-grid ${activeSection === "alerts" ? "alerts-management-grid" : ""}`} aria-label={activeSection === "overview" ? "Intelligence" : "Alert management"}>
            <article className="panel alerts-panel">
              <div className="panel-heading"><div><div className="panel-title">{activeSection === "overview" ? "Alert activity" : "Alerts and rules"} <span className="alert-count">{alerts.length}</span></div><div className="panel-subtitle">Rules and recent triggers</div></div>
                {activeSection === "alerts"
                  ? <button className="add-rule" aria-label="Create alert rule" onClick={() => setShowRuleForm(true)}><Plus size={15} /></button>
                  : <button className="text-link" onClick={() => navigateTo("alerts")}>Manage alerts<ArrowRight size={13} /></button>}
              </div>
              {alerts.length > 0 ? <div className="alert-feed">{alerts.slice(0, activeSection === "overview" ? 2 : 20).map((alert) => <div className="alert-item" key={alert.id}><span className="alert-icon"><ShieldAlert size={15} /></span><div className="alert-copy"><b>{alert.rule_name}</b><p>{alert.message}</p><small>{formatDate(alert.triggered_at)}</small></div></div>)}</div> : <div className="no-alerts"><span className="no-alert-icon"><Check size={19} /></span><b>All quiet for now</b><span>No alert rules have triggered.</span></div>}
              <div className="rules-section"><div className="rules-title">ACTIVE RULES {activeSection === "alerts" && <button onClick={() => setShowRuleForm(true)}><Plus size={12} />New rule</button>}</div>
                {rules.length ? rules.slice(0, activeSection === "overview" ? 3 : undefined).map((rule) => <div className="rule-row" key={rule.id}><span className="rule-status" /><span className="rule-name">{rule.name}</span><span className="rule-condition">&gt; {rule.threshold} errors / {rule.window_minutes}m</span></div>) : <p className="rules-empty">{activeSection === "overview" ? "No active rules. Visit Alerts to create one." : "Create a rule to watch for error bursts."}</p>}
              </div>
            </article>
            {activeSection === "overview" && <>
            <article className="panel anomaly-panel" id="anomalies">
              <div className="panel-heading"><div><div className="panel-title">Anomaly detection <span className="alert-count">{anomalies.length}</span></div><div className="panel-subtitle">Robust z-score (median / MAD) over the last hour</div></div></div>
              {anomalies.length ? <div className="insight-list">{anomalies.slice(0, 6).map((item) => (
                <div className="insight-row" key={`${item.metric}-${item.bucket}`}>
                  <span className={`level-chip level-${item.level}`}>{item.level.toUpperCase()}</span>
                  <div className="insight-copy"><b>{item.observed} {item.metric === "errors" ? "errors" : "events"} / min</b><p>Expected about {item.expected} · score {item.score} · {formatTime(item.bucket)}</p></div>
                </div>
              ))}</div> : <div className="insight-empty"><Sparkles size={17} />No unusual activity. The detector learns what normal looks like for your logs.</div>}
            </article>
            <article className="panel cluster-panel" id="patterns">
              <div className="panel-heading"><div><div className="panel-title">Error patterns</div><div className="panel-subtitle">Similar messages grouped into templates (last hour)</div></div></div>
              {clusters.length ? <div className="insight-list">{clusters.map((item) => (
                <div className="insight-row" key={item.id}>
                  <span className="cluster-count">{item.count}</span>
                  <div className="insight-copy"><b className="cluster-template" title={item.example}>{item.template}</b><p><SeverityPill severity={item.severity} /> {item.services.join(", ")} · last {formatTime(item.last_seen)}</p></div>
                </div>
              ))}</div> : <div className="insight-empty"><Terminal size={17} />No log patterns yet. Generate or import events.</div>}
            </article>
            </>}
          </section>}
          <footer className="page-footer"><span><Signal size={12} />Real-Time Log Analyzer local workspace</span><span>Data stored locally in SQLite <span className="footer-dot">·</span> {new Date().toLocaleDateString()}</span></footer>
        </div>
      </main>

      {showRuleForm && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowRuleForm(false); }}>
        <form className="rule-modal" onSubmit={(event) => void onCreateRule(event)}>
          <div className="modal-icon"><Bell size={18} /></div><button className="modal-close" type="button" aria-label="Close" onClick={() => setShowRuleForm(false)}>×</button>
          <h2>Create alert rule</h2><p>Get notified when error volume crosses a threshold.</p>
          <label>Rule name<input required maxLength={80} placeholder="e.g. Checkout error spike" value={ruleName} onChange={(event) => setRuleName(event.target.value)} /></label>
          <div className="form-pair"><label>Error threshold<input required type="number" min="1" max="100000" value={threshold} onChange={(event) => setThreshold(event.target.value)} /></label><label>Time window (min)<input required type="number" min="1" max="1440" value={windowMinutes} onChange={(event) => setWindowMinutes(event.target.value)} /></label></div>
          <div className="rule-preview"><AlertTriangle size={15} />Trigger when more than <b>{threshold || "N"}</b> errors occur in <b>{windowMinutes || "M"}</b> minutes.</div>
          <div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setShowRuleForm(false)}>Cancel</button><button className="button button-primary" type="submit"><Plus size={15} />Create rule</button></div>
        </form>
      </div>}
      {showSaveSearchForm && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowSaveSearchForm(false); }}>
        <form className="rule-modal" role="dialog" aria-modal="true" aria-labelledby="save-search-title" onSubmit={onSaveSearch}>
          <div className="modal-icon"><Search size={18} /></div>
          <button className="modal-close" type="button" aria-label="Close" onClick={() => setShowSaveSearchForm(false)}>×</button>
          <h2 id="save-search-title">Save this search</h2>
          <p>Keep the current query, severity, service, and time range for quick access later.</p>
          <label className="saved-search-name">Search name<input autoFocus required maxLength={80} value={savedSearchName} onChange={(event) => setSavedSearchName(event.target.value)} placeholder="e.g. Checkout errors" /></label>
          <div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setShowSaveSearchForm(false)}>Cancel</button><button className="button button-primary" type="submit" disabled={!savedSearchName.trim()}><Check size={14} />Save search</button></div>
        </form>
      </div>}
      {showKeyManager && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeKeyManager(); }}>
        <section className="rule-modal ingest-keys-modal" role="dialog" aria-modal="true" aria-labelledby="ingest-keys-title">
          <div className="modal-icon"><KeyRound size={18} /></div>
          <button className="modal-close" type="button" aria-label="Close" onClick={closeKeyManager}>×</button>
          <h2 id="ingest-keys-title">Ingestion keys</h2>
          <p>Create credentials for applications that send logs to your private workspace. You can have up to 10 active keys.</p>
          {keyManagerError && <div className="key-manager-error" role="alert">{keyManagerError}</div>}
          {createdIngestKey && <div className="created-key-notice">
            <b>Copy this key now</b><span>It will not be shown again.</span>
            <div className="created-key-value"><code>{createdIngestKey.key}</code><button type="button" aria-label="Copy ingestion key" onClick={() => void copyIngestKey()}><Copy size={14} /></button></div>
            <small>Send it in the <code>X-API-Key</code> header when posting to <code>/api/ingest</code>.</small>
          </div>}
          <div className="ingest-key-list" aria-label="Active ingestion keys">
            {ingestKeys.map((key) => <div className="ingest-key-row" key={key.id}>
              <span className="ingest-key-icon"><KeyRound size={14} /></span>
              <span className="ingest-key-copy"><b>{key.name}</b><small>Created {new Date(key.created_at).toLocaleDateString()}</small></span>
              <button type="button" className="revoke-key-button" aria-label={`Revoke ${key.name}`} disabled={keyManagerBusy} onClick={() => void onRevokeIngestKey(key)}><Trash2 size={14} /></button>
            </div>)}
            {!ingestKeys.length && keyListLoaded && <div className="ingest-key-empty">No active ingestion keys yet.</div>}
          </div>
          {keyListLoaded && ingestKeys.length < 10 && <form className="create-key-form" onSubmit={(event) => void onCreateIngestKey(event)}>
            <label htmlFor="ingest-key-name">New key name</label>
            <div className="create-key-controls"><input id="ingest-key-name" required minLength={1} maxLength={80} placeholder="e.g. Production API" value={keyName} onChange={(event) => setKeyName(event.target.value)} /><button className="button button-primary" type="submit" disabled={keyManagerBusy || !keyName.trim()}>{keyManagerBusy ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}Create key</button></div>
          </form>}
          {keyListLoaded && ingestKeys.length >= 10 && <p className="key-limit-note">10 of 10 active keys. Revoke a key before creating another.</p>}
          <div className="modal-actions"><button className="button button-secondary" type="button" onClick={closeKeyManager}>Done</button></div>
        </section>
      </div>}
      <button className="floating-command" aria-label="Keyboard shortcuts"><Command size={15} /></button>
    </div>
  );
}

export default App;
