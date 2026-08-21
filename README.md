# Tangerine

Tangerine is an AI-driven DSA (data structures & algorithms) learning platform: chat-based
intent capture, LLM-generated curricula and problems, a persistent problem bank, and
deterministic, hash-verified code execution and evaluation.

## Core Features

### Security and Hashing
- Automated SHA-256 hashing of test case outputs.
- Expected outputs are never stored in plain text or exposed to the runner.
- Secure local file system browsing for source file selection.

### Runner
- Real-time execution and stdout tracking.
- Automated verification against hashed expectations.
- Support for Python, JavaScript, C, C++, and Java.

## Setup

### Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js + pnpm (frontend build only — nothing Node-based runs at request time)
- Local compilers/runtimes for targeted languages (gcc, g++, python3, java, node)
- A `GEMINI_API_KEY` for curriculum/problem generation (see `agent/.env.example`)

### Installation
```bash
pnpm install
cd agent && uv sync
```

### Development
Two processes: the agent (API) and the frontend's own dev server.
```bash
cd agent && uv run python -m uvicorn app.main:app --reload --port 8000
pnpm dev   # Vite dev server, proxies /api to the agent (see vite.config.ts)
```

### Production Build
A single Docker image builds the frontend and bundles it into the Python agent, which
serves both the static SPA and the API from one process:
```bash
docker compose up --build
```
Or manually: `pnpm build` produces `build/client/`, which the agent serves from
`agent/static/` — copy the build output there before running `uvicorn` standalone.

## Architecture
- **Frontend**: React Router v7 in SPA mode (`ssr: false`) + Tailwind CSS — a plain
  client-rendered app, built to static files, no server-side rendering.
- **Backend**: a single Python (FastAPI) agent — REST API, SQLite persistence, LangGraph
  LLM workflows (Gemini), code execution, and static file serving all in one process.
  See `agent/app/` for the feature-oriented module layout.
- **Execution**: `LocalSubprocessExecutor` (direct subprocess, timeout-only) by default;
  swap for `CitronAdapter` (real sandbox isolation, see `API_DOCS.md`) once Citron's own
  image is buildable — both implement the same `CodeExecutor` interface.
- **Styling**: Strict monochrome design system for high-contrast visibility.
