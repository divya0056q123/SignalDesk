import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_PROXY_TARGET || "http://localhost:8000";
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": backend,
        "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (id.includes("/node_modules/recharts/") || id.includes("/node_modules/d3-")) {
              return "charts";
            }
          },
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test-setup.ts",
    },
  };
});
