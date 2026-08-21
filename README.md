# Tangerine

Tangerine is an AI-driven DSA (data structures & algorithms) learning platform: chat-based
intent capture, LLM-generated curricula and problems, a persistent problem bank, and
deterministic, hash-verified code execution and evaluation.

## Core Features

### Security and Hashing
- Automated SHA-256 hashing of test case outputs.
- Expected outputs are never stored in plain text or exposed to the runner.
### Runner
- Real-time execution and stdout tracking.
- Automated verification against hashed expectations.
- Support for Python, C, C++, and Java — executed in the Citron sandbox.

## Setup

### Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js + pnpm (frontend build only — nothing Node-based runs at request time)
- A running [Citron](https://github.com/JustModo/citron) sandbox for code execution
- A `GEMINI_API_KEY` for curriculum/problem generation — copy `.env.example` to `.env`
  at the repo root. This file is for local development only; see below for Docker.

### Installation
```bash
pnpm install
cd agent && uv sync
```

### Development
```bash
pnpm dev
```
`scripts/run.js dev` (Windows/macOS/Linux, Node only — no bash) — starts the agent in
`--reload` mode and the Vite dev server together; the dev server proxies `/api/*` to the
agent (see `vite.config.ts`). `PORT` overrides the agent's port (default `8000`).

### Production
```bash
pnpm start
```
`scripts/run.js prod` — builds the SPA, stages it into `agent/static/`, and runs the
agent alone serving both the static frontend and the API from one process. Or via
Docker, which does the same thing in a single image:
```bash
docker compose up --build
```
The compose stack publishes **only** the web UI (`PORT`, default `8000`); the Citron
sandbox runs on an internal network with no host binding. No `.env` is used — open the
app and enter your Gemini API key when prompted. It's verified against Google before it's
accepted and stored encrypted on the `agent-data` volume, so it survives restarts.

## Architecture
- **Frontend**: React Router v7 in SPA mode (`ssr: false`) + Tailwind CSS — a plain
  client-rendered app, built to static files, no server-side rendering.
- **Backend**: a single Python (FastAPI) agent — REST API, SQLite persistence, LangGraph
  LLM workflows (Gemini), code execution, and static file serving all in one process.
  See `agent/app/` for the feature-oriented module layout.
- **Execution**: `CitronAdapter` only — every submission runs in the Citron sandbox
  (nsjail isolation). Nothing executes learner code in the agent process.
- **Configuration**: fixed deployment settings live in `agent/app/shared/config.py` (env or
  compose); the Gemini key is user-supplied at runtime and stored encrypted in SQLite
  (`agent/app/shared/secrets.py`).
- **Styling**: Strict monochrome design system for high-contrast visibility.
