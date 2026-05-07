# Multi-stage build: pnpm install + Vite build, then nginx:alpine to serve dist.
# Caddy reverse-proxies / to this container; nginx itself only handles SPA
# fallback + asset cache headers and listens on port 80.

FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.0.0 --activate

# Install before sources so the cache is reused when only sources change.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm routes:generate \
    && pnpm build


FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1/index.html || exit 1
