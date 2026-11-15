import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const api = vi.hoisted(() => ({
  createRule: vi.fn(),
  fetchAlerts: vi.fn(),
  fetchAnomalies: vi.fn(),
  fetchClusters: vi.fn(),
  fetchLogs: vi.fn(),
  fetchMetrics: vi.fn(),
  fetchRules: vi.fn(),
  fetchServices: vi.fn(),
  fetchTimeline: vi.fn(),
  generateLogs: vi.fn(),
  uploadLogFile: vi.fn(),
  websocketUrl: vi.fn(() => "ws://localhost/ws/logs"),
}));

vi.mock("./api", () => api);

class MockWebSocket {
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(_url: string) {}

  close() {
    this.readyState = 3;
  }
}

describe("App navigation and account controls", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    vi.stubGlobal("WebSocket", MockWebSocket);
    api.fetchLogs.mockResolvedValue([]);
    api.fetchMetrics.mockResolvedValue({ total_events: 0, error_rate: 0, events_per_second: 0, by_severity: {} });
    api.fetchTimeline.mockResolvedValue([]);
    api.fetchRules.mockResolvedValue([]);
    api.fetchAlerts.mockResolvedValue([]);
    api.fetchServices.mockResolvedValue([]);
    api.fetchAnomalies.mockResolvedValue([]);
    api.fetchClusters.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    Reflect.deleteProperty(window.navigator, "clipboard");
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("opens useful notification, profile, and workspace menus", () => {
    render(<App username="divyanshi" onSignOut={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeTruthy();
    expect(screen.getByText(/No recent notifications/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    const accountMenu = screen.getByRole("dialog", { name: "Account" });
    expect(within(accountMenu).getByText("divyanshi")).toBeTruthy();
    expect(within(accountMenu).getByRole("button", { name: "Sign out" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /divyanshi's workspace/ }));
    expect(screen.getByRole("dialog", { name: "Workspace details" })).toBeTruthy();
    expect(screen.getByText(/private to this account/)).toBeTruthy();
  });

  it("updates the selected navigation and breadcrumb when moving between sections", async () => {
    const { container } = render(<App username="divyanshi" />);

    expect(screen.getByText("DETECTED SERVICES")).toBeTruthy();
    expect(screen.getByText("Services are identified from incoming logs.")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Import logs to discover services/ })).toBeTruthy();
    expect(container.querySelector('nav a[href="#overview"] img[src="/icons/overview.svg"]')).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: /Alerts/ }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#alerts");
      expect(container.querySelector('nav a[href="#alerts"]')?.getAttribute("aria-current")).toBe("page");
    });
    expect(screen.getByRole("heading", { name: "Manage alerts" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Create alert rule" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Import logs" })).toBeNull();
    expect(screen.getByRole("link", { name: "Workspace" })).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "Workspace" }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#overview");
      expect(container.querySelector('nav a[href="#overview"]')?.getAttribute("aria-current")).toBe("page");
    });
    expect(screen.getByRole("heading", { name: /Good afternoon, divyanshi/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Manage alerts" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create alert rule" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Search logs" })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: /Log explorer/ }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#logs");
      expect(container.querySelector('nav a[href="#logs"]')?.getAttribute("aria-current")).toBe("page");
    });
    expect(screen.getByRole("heading", { name: "Explore your logs" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Search logs" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import logs" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create alert rule" })).toBeNull();
  });

  it("loads shareable filters and saves searches for later use", async () => {
    window.history.replaceState({}, "", "/?q=timeout&severity=ERROR&range=24h#logs");
    const { unmount } = render(<App username="divyanshi" />);

    expect((screen.getByRole("textbox", { name: "Search logs" }) as HTMLInputElement).value).toBe("timeout");
    expect((screen.getByRole("combobox", { name: "Filter by severity" }) as HTMLSelectElement).value).toBe("ERROR");
    expect((screen.getByRole("combobox", { name: "Filter by time range" }) as HTMLSelectElement).value).toBe("24h");
    await waitFor(() => {
      expect(window.location.search).toContain("q=timeout");
      expect(window.location.search).toContain("severity=ERROR");
    });

    fireEvent.click(screen.getByRole("button", { name: "Save search" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search name" }), { target: { value: "Timeout errors" } });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Save this search" })).getByRole("button", { name: "Save search" }));
    const savedSearch = await screen.findByRole("option", { name: "Timeout errors" });

    fireEvent.change(screen.getByRole("textbox", { name: "Search logs" }), { target: { value: "another query" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Saved searches" }), { target: { value: savedSearch.getAttribute("value") } });
    expect((screen.getByRole("textbox", { name: "Search logs" }) as HTMLInputElement).value).toBe("timeout");

    unmount();
    render(<App username="divyanshi" />);
    expect(await screen.findByRole("option", { name: "Timeout errors" })).toBeTruthy();
  });

  it("copies a shareable URL for the active filters", async () => {
    window.location.hash = "#logs";
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<App username="divyanshi" />);

    fireEvent.change(screen.getByRole("textbox", { name: "Search logs" }), { target: { value: "payment failed" } });
    await waitFor(() => expect(window.location.search).toContain("q=payment+failed"));
    fireEvent.click(screen.getByRole("button", { name: "Share filters" }));

    await waitFor(() => expect(screen.getByText("Shareable log search URL copied.")).toBeTruthy());
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("q=payment+failed"));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("#logs"));
  });

  it("exports the filtered log results as CSV and JSON", async () => {
    window.location.hash = "#logs";
    api.fetchLogs.mockResolvedValue([{
      id: 1,
      timestamp: "2026-11-14T12:30:00Z",
      severity: "ERROR",
      service: "payments",
      source: "checkout.ts",
      message: 'provider said "retry", then failed',
    }]);
    const exportedBlobs: Blob[] = [];
    class URLWithBlobSupport extends URL {
      static createObjectURL = vi.fn((blob: Blob) => {
        exportedBlobs.push(blob);
        return `blob:export-${exportedBlobs.length}`;
      });
      static revokeObjectURL = vi.fn();
    }
    vi.stubGlobal("URL", URLWithBlobSupport);
    const downloadClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<App username="divyanshi" />);

    await screen.findByText('provider said "retry", then failed');
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));

    expect(downloadClick).toHaveBeenCalledTimes(2);
    expect(exportedBlobs[0].type).toContain("text/csv");
    expect(exportedBlobs[1].type).toContain("application/json");
    const readBlob = (blob: Blob) => new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    const csv = await readBlob(exportedBlobs[0]);
    const json = JSON.parse(await readBlob(exportedBlobs[1])) as Array<{ message: string; severity: string }>;
    expect(csv).toContain('"timestamp","severity","service","source","message"');
    expect(csv).toContain('"provider said ""retry"", then failed"');
    expect(json[0]).toMatchObject({ severity: "ERROR", message: 'provider said "retry", then failed' });
    expect(screen.getByText("Exported 1 filtered events as JSON.")).toBeTruthy();
  });
});
