import path from "node:path";
import react from "@vitejs/plugin-react";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";
import { defineConfig } from "vitest/config";

// In dev we proxy API + auth + admin to the backend so cookies stay first-party.
// In production Caddy fronts both the static SPA and the API on the same origin.
export default defineConfig({
  plugins: [
    TanStackRouterVite({ routesDirectory: "./src/routes" }),
    react(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // The SPA hits /api/* and Caddy strips the prefix in production. In dev
    // we mirror that: proxy /api/* to localhost:8000 and rewrite away the
    // /api so the backend (which is mounted at root) sees the original path.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
