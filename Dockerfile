# Single consolidated image: Python agent serves both the API and the built SPA.
# (No more separate web/agent images — see docker-compose.yml.)

FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY app ./app
COPY public ./public
COPY react-router.config.ts vite.config.ts tsconfig.json components.json ./
RUN pnpm run build


FROM python:3.12-slim AS runtime
WORKDIR /app

# c/cpp/java/python execution happens in the citron service (real nsjail isolation) —
# this image only needs a JS runtime for CompositeExecutor's LocalSubprocessExecutor
# fallback, since Citron's languages.toml has no JS runtime registered.
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev

COPY agent/app ./app
COPY agent/migrations ./migrations
COPY --from=frontend-build /app/build/client ./static

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
