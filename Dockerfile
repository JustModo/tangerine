# Single consolidated image: Python agent serves both the API and the built SPA.
# (No more separate web/agent images — see docker-compose.yml.)

# Reads the commit hash from .git at build time, inside the container — so it works the
# same on every host OS with plain `docker compose up --build`, no env var to export.
FROM alpine/git:v2.45.2 AS gitinfo
WORKDIR /repo
COPY .git ./.git
RUN git rev-parse HEAD > /git-sha.txt

FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# pnpm 11 needs Node 22+ (node:20 fails with ERR_UNKNOWN_BUILTIN_MODULE on corepack).
RUN corepack enable && corepack prepare pnpm@11.22.0 --activate && pnpm install --frozen-lockfile
COPY app ./app
COPY public ./public
COPY react-router.config.ts vite.config.ts tsconfig.json components.json ./
RUN pnpm run build


FROM python:3.12-slim AS runtime
WORKDIR /app

# No language runtimes here on purpose: all learner code executes in the citron service,
# under real nsjail isolation. This image only runs the agent and serves static files.
RUN pip install --no-cache-dir uv

COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev

COPY agent/app ./app
COPY agent/migrations ./migrations
COPY --from=frontend-build /app/build/client ./static
COPY --from=gitinfo /git-sha.txt ./GIT_SHA

ENV PATH="/app/.venv/bin:$PATH"
# Both the SQLite DB and the encryption key for user-supplied secrets live here, so this
# must be a volume for the Gemini key to survive `docker compose down`.
ENV DATABASE_PATH=/data/agent.db
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
