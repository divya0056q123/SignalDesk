import { describe, expect, it } from "vitest";
import { buildLogQuery } from "./api";
import type { LogFilters } from "./types";

describe("buildLogQuery", () => {
  it("includes only active filters and always requests a bounded page", () => {
    const filters: LogFilters = {
      search: "  timeout  ",
      severity: "ERROR",
      service: "payments",
      range: "all",
    };
    const query = new URLSearchParams(buildLogQuery(filters));
    expect(query.get("search")).toBe("timeout");
    expect(query.get("severity")).toBe("ERROR");
    expect(query.get("service")).toBe("payments");
    expect(query.has("start")).toBe(false);
    expect(query.get("limit")).toBe("200");
  });

  it("applies a valid ISO time boundary for a selected range", () => {
    const query = new URLSearchParams(buildLogQuery({
      search: "", severity: "", service: "", range: "15m",
    }));
    expect(new Date(query.get("start")!).getTime()).toBeGreaterThan(Date.now() - 16 * 60_000);
    expect(new Date(query.get("start")!).getTime()).toBeLessThanOrEqual(Date.now());
  });
});
