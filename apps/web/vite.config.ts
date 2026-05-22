import { createHash } from "node:crypto";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";
import { defineConfig, type Plugin } from "vitest/config";

// Subresource-Integrity plugin. After Rollup emits the bundle, we compute a
// SHA-384 hash over every chunk + asset and patch the `<script>` / `<link>`
// tags in index.html with matching `integrity=` attributes. The hash
// defends against a tampered cache/edge layer between the static host
// (nginx) and the user's browser — Caddy is in front today but a future
// CDN cache could be added without losing the guarantee.
function subresourceIntegrity(): Plugin {
  return {
    name: "magister-sri",
    apply: "build",
    enforce: "post",
    generateBundle(_options, bundle) {
      const integrity = new Map<string, string>();
      for (const [name, chunk] of Object.entries(bundle)) {
        const source =
          chunk.type === "chunk"
            ? chunk.code
            : typeof chunk.source === "string"
              ? chunk.source
              : Buffer.from(chunk.source);
        const digest = createHash("sha384").update(source).digest("base64");
        integrity.set(name, `sha384-${digest}`);
      }
      const index = bundle["index.html"];
      if (!index || index.type !== "asset" || typeof index.source !== "string") {
        return;
      }
      const fileFromHref = (href: string): string =>
        href.startsWith("/") ? href.slice(1) : href;
      const ensureCrossorigin = (s: string): string =>
        /\bcrossorigin(=|\s|>)/.test(s) ? s : `${s} crossorigin="anonymous"`;
      let html = index.source;
      html = html.replace(
        /<script\b([^>]*?)\ssrc="([^"]+)"([^>]*)>/g,
        (match, pre, src, post) => {
          const hash = integrity.get(fileFromHref(src));
          if (!hash) return match;
          if (/\sintegrity=/.test(match)) return match;
          const attrs = ensureCrossorigin(`${pre} src="${src}"${post}`);
          return `<script${attrs} integrity="${hash}">`;
        },
      );
      html = html.replace(
        /<link\b([^>]*?)\shref="([^"]+)"([^>]*)>/g,
        (match, pre, href, post) => {
          if (!/rel="(stylesheet|modulepreload|preload)"/.test(match)) return match;
          const hash = integrity.get(fileFromHref(href));
          if (!hash) return match;
          if (/\sintegrity=/.test(match)) return match;
          const attrs = ensureCrossorigin(`${pre} href="${href}"${post}`);
          return `<link${attrs} integrity="${hash}">`;
        },
      );
      index.source = html;
    },
  };
}

// In dev we proxy API + auth + admin to the backend so cookies stay first-party.
// In production Caddy fronts both the static SPA and the API on the same origin.
export default defineConfig({
  plugins: [
    TanStackRouterVite({ routesDirectory: "./src/routes" }),
    react(),
    subresourceIntegrity(),
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
    // Disable the modulepreload polyfill — it injects an inline <script>
    // into index.html that would force `'unsafe-inline'` (or per-build
    // hashing) in the Content-Security-Policy. Our es2022 target only
    // ships to browsers with native modulepreload, so the polyfill is
    // dead weight anyway.
    modulePreload: { polyfill: false },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
