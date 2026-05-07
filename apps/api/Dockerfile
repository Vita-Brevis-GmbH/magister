# Magister API — multi-stage build with uv

# --- Builder ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

# Install uv (pinned to a stable line; can be bumped via build-arg).
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifest first to maximise layer-cache reuse on rebuilds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy the source and install the project itself.
COPY magister_api ./magister_api
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev

# --- Runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    MAGISTER_LOG_LEVEL=INFO

# Run as non-root.
RUN groupadd --system --gid 1000 magister \
 && useradd  --system --uid 1000 --gid magister --create-home --home-dir /app magister

# Minimal runtime libs: libldap is needed by ldap3 only when using GSSAPI; we
# stay on plain SIMPLE+TLS so no extra system packages required. Keep the
# image small.

WORKDIR /app
COPY --from=builder --chown=magister:magister /app /app
RUN chmod +x /app/docker-entrypoint.sh

USER magister
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "magister_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
