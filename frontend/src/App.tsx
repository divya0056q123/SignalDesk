import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, Bell, Check, ChevronDown, CircleHelp,
  Clock3, Command, FileUp, Filter, Gauge, LayoutDashboard, ListFilter, LoaderCircle,
  MoreHorizontal, Plus, Radio, Search, Server, ShieldAlert, Signal, Sparkles, Terminal,
  Zap,
} from "lucide-react";
import {
  createRule, fetchAlerts, fetchLogs, fetchMetrics, fetchRules, fetchServices, fetchTimeline,
  generateLogs, uploadLogFile, websocketUrl,
} from "./api";
import type { AlertRule, LogEvent, LogFilters, Metrics, TimelinePoint, TriggeredAlert } from "./types";

const emptyMetrics: Metrics = {
  total_events: 0, error_rate: 0, events_per_second: 0, by_severity: {},
};
const initialFilters: LogFilters = { search: "", severity: "", service: "", range: "1h" };

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
  label: string; value: string; detail: string; icon: typeof Activity; tone: string; trend?: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon size={16} /></span></div>
      <div className="metric-value">{value}{trend && <span className="metric-trend">{trend}</span>}</div>
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
          <line x1={left} y1={y} x2={width - right} y2={y} stroke="#232b35" strokeDasharray="3 5" />
          <text x={left - 7} y={y + 3} textAnchor="end" fill="#747f8d" fontSize="9">{Math.round(maximum * ratio)}</text>
        </g>;
      })}
      {points.map((point, index) => {
        const x = left + index * step;
        const totalHeight = (point.total / maximum) * plotHeight;
        const errorHeight = (point.errors / maximum) * plotHeight;
        return <g key={point.bucket}>
          <title>{`${new Date(point.bucket).toLocaleString()}: ${point.total} events, ${point.errors} errors${point.spike ? " · error spike" : ""}`}</title>
          <rect x={x + step * 0.14} y={top + plotHeight - totalHeight} width={Math.max(1, step * 0.56)} height={totalHeight} rx="2" fill={point.spike ? "#fb7185" : "#8173f1"} fillOpacity={point.spike ? 1 : 0.76} />
          {point.errors > 0 && <rect x={x + step * 0.72} y={top + plotHeight - errorHeight} width={Math.max(1, step * 0.2)} height={errorHeight} rx="1" fill="#f0a04b" />}
        </g>;
      })}
      {labelIndexes.map((index) => points[index] && <text key={index} x={left + index * step + step / 2} y="146" textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"} fill="#747f8d" fontSize="9">
        {new Date(points[index].bucket).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
      </text>)}
    </svg>
  );
}

function App() {
  const [filters, setFilters] = useState(initialFilters);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [metrics, setMetrics] = useState(emptyMetrics);
  const [timeline, setTimeline] = useState<TimelinePoint[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [alerts, setAlerts] = useState<TriggeredAlert[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [ruleName, setRuleName] = useState("");
  const [threshold, setThreshold] = useState("5");
  const [windowMinutes, setWindowMinutes] = useState("5");
  const fileRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const filtersRef = useRef(filters);
  const refreshTimer = useRef<number | undefined>(undefined);
  const streamRefreshTimer = useRef<number | undefined>(undefined);
  filtersRef.current = filters;

  const refreshDashboard = useCallback(async () => {
    try {
      const [nextLogs, nextMetrics, nextTimeline, nextRules, nextAlerts, nextServices] = await Promise.all([
        fetchLogs(filters), fetchMetrics(), fetchTimeline(), fetchRules(), fetchAlerts(), fetchServices(),
      ]);
      setLogs(nextLogs);
      setMetrics(nextMetrics);
      setTimeline(nextTimeline);
      setRules(nextRules);
      setAlerts(nextAlerts);
      setServices(nextServices);
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
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void Promise.all([fetchMetrics(), fetchTimeline(), fetchAlerts()])
        .then(([nextMetrics, nextTimeline, nextAlerts]) => {
          setMetrics(nextMetrics); setTimeline(nextTimeline); setAlerts(nextAlerts);
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
          const event = JSON.parse(message.data) as { type: string; data: LogEvent | TriggeredAlert };
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

  const maxSeverity = Math.max(1, ...severityCounts.map((item) => item.count));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="SignalDesk home">
          <span className="brand-mark"><Activity size={19} strokeWidth={2.5} /></span>
          <span>signal<span>desk</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <button className="workspace-switch">
          <span className="workspace-avatar">A</span><span className="workspace-copy"><b>Acme Systems</b><small>Free workspace</small></span>
          <ChevronDown size={15} />
        </button>
        <div className="nav-label">OBSERVABILITY</div>
        <nav className="side-nav" aria-label="Main navigation">
          <a className="nav-link selected" href="#overview"><LayoutDashboard size={17} />Overview<span className="nav-active" /></a>
          <a className="nav-link" href="#logs"><Terminal size={17} />Log explorer</a>
          <a className="nav-link" href="#alerts"><Bell size={17} />Alerts{alerts.length > 0 && <span className="nav-count">{alerts.length}</span>}</a>
        </nav>
        <div className="nav-label sources-label">SOURCES</div>
        <div className="source-list">
          {services.slice(0, 5).map((service) => <div className="source-item" key={service}><span className="source-dot" />{service}<span className="source-live">live</span></div>)}
          {services.length === 0 && <div className="source-empty">Waiting for services…</div>}
        </div>
        <div className="sidebar-bottom">
          <div className="plan-card"><span className="plan-icon"><Sparkles size={15} /></span><b>Make it yours</b><p>SignalDesk is running locally with your sample data.</p><button onClick={() => void runGenerator()}>Generate events <ArrowDownToLine size={13} /></button></div>
          <a className="nav-link help-link" href="https://fastapi.tiangolo.com/" target="_blank" rel="noreferrer"><CircleHelp size={16} />Documentation</a>
          <div className="user-profile"><span className="user-avatar">DS</span><span><b>Divyanshi</b><small>Local administrator</small></span><MoreHorizontal size={18} /></div>
        </div>
      </aside>

      <main className="main-area" id="overview">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-divider">/</span><b>Overview</b></div>
          <div className="top-actions">
            <div className={`connection-pill ${connected ? "is-connected" : ""}`}><span />{connected ? "Live connected" : "Connecting"}</div>
            <button className="icon-button" aria-label="Notifications"><Bell size={17} />{alerts.length > 0 && <i />}</button>
            <span className="top-avatar">DS</span>
          </div>
        </header>

        <div className="content-wrap">
          <section className="page-heading">
            <div><div className="eyebrow"><span className="eyebrow-line" />SYSTEM OVERVIEW</div><h1>Good afternoon, Divyanshi <span className="wave">✦</span></h1><p>Here’s what’s happening across your services right now.</p></div>
            <div className="heading-actions">
              <button className="button button-secondary" onClick={() => fileRef.current?.click()} disabled={busy}><FileUp size={15} />Import logs</button>
              <input ref={fileRef} type="file" accept=".log,.txt,text/plain" hidden onChange={(event) => void onFileChange(event)} />
              <button className="button button-primary" onClick={() => void runGenerator()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Zap size={15} />}Generate events</button>
            </div>
          </section>

          {(error || notice) && <div className={`toast ${error ? "toast-error" : ""}`} role="status"><span>{error || notice}</span><button aria-label="Dismiss message" onClick={() => { setError(""); setNotice(""); }}>×</button></div>}

          <section className="metric-grid" aria-label="Live metrics">
            <MetricCard label="Total events" value={metrics.total_events.toLocaleString()} detail="All time · across your services" icon={Activity} tone="violet" />
            <MetricCard label="Error rate" value={`${(metrics.error_rate * 100).toFixed(1)}%`} detail="Errors + critical events" icon={AlertTriangle} tone="rose" trend={metrics.error_rate > 0.1 ? "Elevated" : undefined} />
            <MetricCard label="Events / second" value={metrics.events_per_second.toFixed(2)} detail="Rolling 60-second window" icon={Gauge} tone="blue" />
            <MetricCard label="Active services" value={String(services.length).padStart(2, "0")} detail="Reporting in this workspace" icon={Server} tone="mint" />
          </section>

          <section className="visual-grid">
            <article className="panel chart-panel">
              <div className="panel-heading"><div><div className="panel-title">Event volume</div><div className="panel-subtitle">Log activity over the last 60 minutes</div></div><div className="chart-legend"><span><i className="legend-events" />Events</span><span><i className="legend-errors" />Errors</span><button className="select-small"><Clock3 size={13} />Last hour<ChevronDown size={13} /></button></div></div>
              <div className="chart-wrap">
                {timeline.length ? <EventTimeline points={timeline} /> : <div className="chart-empty"><Activity size={19} />Waiting for timeline data</div>}
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
          </section>

          <section className="lower-grid">
            <article className="panel log-panel" id="logs">
              <div className="panel-heading log-heading"><div><div className="panel-title">Live log stream <span className="live-tag"><i />LIVE</span></div><div className="panel-subtitle">Search, filter, and inspect incoming events</div></div><button className="icon-button subtle" aria-label="Log table options"><MoreHorizontal size={18} /></button></div>
              <div className="filter-toolbar">
                <label className="search-input"><Search size={15} /><input ref={searchRef} aria-label="Search logs" placeholder="Search messages, services…" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} /><kbd>⌘ K</kbd></label>
                <label className="filter-select"><Filter size={13} /><select aria-label="Filter by severity" value={filters.severity} onChange={(event) => setFilters({ ...filters, severity: event.target.value })}><option value="">All levels</option><option>CRITICAL</option><option>ERROR</option><option>WARNING</option><option>INFO</option><option>DEBUG</option><option>UNKNOWN</option></select><ChevronDown size={13} /></label>
                <label className="filter-select"><ListFilter size={13} /><select aria-label="Filter by service" value={filters.service} onChange={(event) => setFilters({ ...filters, service: event.target.value })}><option value="">All services</option>{services.map((service) => <option key={service}>{service}</option>)}</select><ChevronDown size={13} /></label>
                <label className="filter-select range-select"><Clock3 size={13} /><select aria-label="Filter by time range" value={filters.range} onChange={(event) => setFilters({ ...filters, range: event.target.value })}><option value="15m">Last 15 min</option><option value="1h">Last hour</option><option value="24h">Last 24 hours</option><option value="all">All time</option></select><ChevronDown size={13} /></label>
              </div>
              <div className="table-scroll">
                <table className="log-table"><thead><tr><th>TIME</th><th>LEVEL</th><th>SERVICE</th><th>MESSAGE</th></tr></thead>
                  <tbody>{logs.map((log) => <tr key={log.id}><td className="time-cell">{formatTime(log.timestamp)}</td><td><SeverityPill severity={log.severity} /></td><td><span className="service-name">{log.service}</span></td><td className="message-cell" title={log.message}>{log.message}</td></tr>)}
                    {!logs.length && <tr><td colSpan={4} className="empty-row">No events match your filters.</td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="table-footer"><span>Showing <b>{logs.length}</b> recent events</span><span className="stream-status"><Radio size={12} />Stream {connected ? "active" : "reconnecting"}</span></div>
            </article>

            <article className="panel alerts-panel" id="alerts">
              <div className="panel-heading"><div><div className="panel-title">Alert activity <span className="alert-count">{alerts.length}</span></div><div className="panel-subtitle">Rules and recent triggers</div></div><button className="add-rule" aria-label="Create alert rule" onClick={() => setShowRuleForm(true)}><Plus size={15} /></button></div>
              {alerts.length > 0 ? <div className="alert-feed">{alerts.slice(0, 4).map((alert) => <div className="alert-item" key={alert.id}><span className="alert-icon"><ShieldAlert size={15} /></span><div className="alert-copy"><b>{alert.rule_name}</b><p>{alert.message}</p><small>{formatDate(alert.triggered_at)}</small></div></div>)}</div> : <div className="no-alerts"><span className="no-alert-icon"><Check size={19} /></span><b>All quiet for now</b><span>No alert rules have triggered.</span></div>}
              <div className="rules-section"><div className="rules-title">ACTIVE RULES <button onClick={() => setShowRuleForm(true)}><Plus size={12} />New rule</button></div>
                {rules.length ? rules.map((rule) => <div className="rule-row" key={rule.id}><span className="rule-status" /><span className="rule-name">{rule.name}</span><span className="rule-condition">&gt; {rule.threshold} errors / {rule.window_minutes}m</span></div>) : <p className="rules-empty">Create a rule to watch for error bursts.</p>}
              </div>
            </article>
          </section>
          <footer className="page-footer"><span><Signal size={12} />SignalDesk local workspace</span><span>Data stored locally in SQLite <span className="footer-dot">·</span> {new Date().toLocaleDateString()}</span></footer>
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
      <button className="floating-command" aria-label="Keyboard shortcuts"><Command size={15} /></button>
    </div>
  );
}

export default App;
