# ── Stage 1: Build frontend ──────────────────────────────────────────────
FROM node:22-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python app ───────────────────────────────────────────────────
FROM python:3.12-slim

# Create a non-root user; app runs as appuser, not root
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

# Install dependencies as root before switching users
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy source
COPY --chown=appuser:appgroup . .

# Overlay built frontend
COPY --from=frontend-builder --chown=appuser:appgroup /app/static ./app/static

# Ensure .env is NOT baked in — it must be injected at runtime via --env-file
# Explicitly remove any accidental .env that might have been copied
RUN rm -f .env

# Runtime directories writable by appuser only
RUN mkdir -p logs && chown -R appuser:appgroup logs /app

# Drop root
USER appuser

# Only expose the app port — no debug ports
EXPOSE 8000

# Use exec form so SIGTERM propagates correctly for graceful restart
CMD ["python", "main.py"]
