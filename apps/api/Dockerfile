# Magister API — multi-stage build with uv

# --- Builder ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

# Pin uv to a tested version. Bumping is a deliberate dep-update PR.
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

# Build toolchain + Kerberos headers so the optional `gssapi` extra (Kerberos
# service bind) compiles. Cheap and keeps the image gssapi-capable out of the box.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libkrb5-dev \
 && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest first to maximise layer-cache reuse on rebuilds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra gssapi

# Now copy the source and install the project itself.
COPY magister_api ./magister_api
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev --extra gssapi

# --- Runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    MAGISTER_LOG_LEVEL=INFO

# Run as non-root.
RUN groupadd --system --gid 1000 magister \
 && useradd  --system --uid 1000 --gid magister --create-home --home-dir /app magister

# Pre-create the shared webserver-cert dir owned by the runtime user. A named
# volume (compose `web_certs`) inherits the ownership of its mountpoint in the
# image on first init; without this the fresh volume is root-owned and the
# non-root API (uid 1000) cannot write /certs/tls.caddy — which silently leaves
# Caddy without its `import /certs/tls.caddy` snippet and unable to start.
RUN mkdir -p /certs && chown magister:magister /certs

# Runtime libs:
# - WeasyPrint (parent-letter + credential PDFs) needs Pango/Cairo/GDK-PixBuf.
# - Kerberos runtime + SASL GSSAPI module + kinit: only exercised when
#   MAGISTER_AD_BIND_MODE=gssapi (Kerberos service bind); harmless otherwise.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 libgdk-pixbuf-2.0-0 \
      libkrb5-3 libsasl2-modules-gssapi-mit krb5-user \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder --chown=magister:magister /app /app
RUN chmod +x /app/docker-entrypoint.sh

USER magister
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "magister_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
