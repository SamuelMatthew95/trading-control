# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# trading-control backend image
#
# Multi-stage build:
#   1. builder — installs dependencies into an isolated virtualenv (with a
#      compiler toolchain available for any sdist fallbacks).
#   2. runtime — slim image, non-root user, only the venv + application code.
#
# Build:    docker build -t trading-control-api .
# Run:      docker run --rm -p 8000:8000 --env-file .env trading-control-api
# Compose:  docker compose up --build        (api + postgres + redis)
# ─────────────────────────────────────────────────────────────────────────────

ARG PYTHON_VERSION=3.11

# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

# Toolchain only exists in this stage; the runtime image never carries it.
# Unpinned apt is deliberate: pins break on Debian point releases and the
# stage is discarded; Python deps are the reproducibility surface.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

# Dependency layer is cached until requirements.txt changes. Packaging tools
# are upgraded first: the stock setuptools 79 vendors jaraco.context 5.3.0
# (CVE-2026-23949) and wheel 0.45.1 (CVE-2026-24049); setuptools >= 82 drops
# the vulnerable vendored copies entirely.
COPY requirements.txt .
# hadolint ignore=DL3013
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="trading-control" \
      org.opencontainers.image.description="Event-driven algorithmic trading platform (FastAPI backend)" \
      org.opencontainers.image.source="https://github.com/SamuelMatthew95/trading-control"

# Run as a dedicated non-root user (uid >= 10000 avoids host uid collisions).
RUN groupadd --gid 10001 trading \
    && useradd --uid 10001 --gid trading --shell /usr/sbin/nologin \
       --no-create-home trading

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Patch the base image's own packaging tools — the stock setuptools/wheel in
# /usr/local carry vendored CVEs (jaraco.context, wheel); see builder note.
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY --from=builder /opt/venv /opt/venv
# Only the backend packages — .dockerignore excludes frontend/tests/docs.
COPY --chown=trading:trading api/ api/
COPY --chown=trading:trading backtest/ backtest/
COPY --chown=trading:trading cognitive/ cognitive/
COPY --chown=trading:trading config/ config/
COPY --chown=trading:trading pyproject.toml ./

USER trading

EXPOSE 8000

# /health answers during the 60s startup grace period ("starting"), so the
# probe passes as soon as the HTTP server binds — matches render.yaml timing.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
        sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4).status == 200 else 1)"

# Single gunicorn worker is intentional: agents + price poller run in-process
# via the FastAPI lifespan, and they are not leader-elected — a second worker
# would double-trade. Scale reads via replicas of a poller-disabled profile.
CMD ["sh", "-c", "exec gunicorn api.main:app -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT} --access-logfile - --error-logfile -"]
