# Backend image — FastAPI + uv, referenced by the Docker Compose example in
# docs/DEPLOYMENT.md (`build: ./apps/backend`).
#
# The base image bundles Python 3.14 (matching apps/backend/.python-version) and
# the uv package manager, so the build mirrors local dev (`uv venv` + `uv pip`).
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

# Do not buffer stdout/stderr — logs appear immediately in `docker logs`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first so this layer is cached until requirements change.
# Runtime-only deps (no dev toolchain) — pinned in requirements.txt.
COPY requirements.txt ./
RUN uv venv && uv pip install -r requirements.txt

# Application code.
COPY app ./app
COPY pytest.ini ./

# DATA_DIR is overridable; default to a stable in-container path that the
# compose file mounts a named volume onto (- batch-data:/data).
ENV DATA_DIR=/data
RUN mkdir -p /data

# Run as a non-root user (defense in depth); ensure it owns the writable data dir.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Default command for standalone `docker run`. The compose file overrides this
# with `--workers 4`. 0.0.0.0 is required for the port to be reachable from the
# proxy — in compose the port is only on the internal network, never published.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-reload"]
