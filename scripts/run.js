#!/usr/bin/env node
// Centralized dev/prod entrypoint — cross-platform (Windows/macOS/Linux), Node.js only
// (no bash), since `uv`/`pnpm` resolution across platforms needs a shell either way.
//   node scripts/run.js dev   — agent in --reload mode + the react-router dev server
//   node scripts/run.js prod  — builds the SPA, stages it into agent/static, runs the agent alone
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(fileURLToPath(import.meta.url), "..", "..");
const agentDir = path.join(rootDir, "agent");
const mode = process.argv[2] || "dev";
const port = process.env.PORT || "8000";

// shell:true so Windows resolves uv.exe/pnpm.cmd via PATH+PATHEXT the same way a
// terminal would — plain child_process.spawn doesn't do that extension lookup itself.
function runSync(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", shell: true, ...options });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function spawnLong(command, args, options = {}) {
  return spawn(command, args, { stdio: "inherit", shell: true, ...options });
}

function isPortFree(candidate) {
  return new Promise((resolve) => {
    const server = net
      .createServer()
      .once("error", () => resolve(false))
      .once("listening", () => server.close(() => resolve(true)))
      .listen(candidate, "127.0.0.1");
  });
}

/** CITRON_URL comes from .env in dev (agent/app/shared/config.py reads the same file). */
function citronUrl() {
  const envFile = path.join(rootDir, ".env");
  if (existsSync(envFile)) {
    const match = readFileSync(envFile, "utf8").match(/^CITRON_URL=(.+)$/m);
    if (match) return match[1].trim();
  }
  return "http://localhost:2358";
}

async function isReachable(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(2500) });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Both of these used to fail silently and look identical from the browser: a stale page.
 * If the Docker `app` service is up it already owns :8000, so the dev agent never binds,
 * and http://localhost:8000 serves the image's baked-in frontend rather than your working
 * tree. Catch it here with the exact command to fix it instead.
 */
async function preflight() {
  if (!(await isPortFree(Number(port)))) {
    console.error(`\n!!  Port ${port} is already in use, so the dev agent cannot start.`);
    console.error("    Most likely the Docker app service is running. Stop it with:\n");
    console.error("      docker compose stop app\n");
    console.error(`    (Anything still served on :${port} is the OLD build, not your code.)`);
    process.exit(1);
  }

  const citron = citronUrl();
  if (await isReachable(`${citron}/ready`)) return;

  console.log(`==> code sandbox not up at ${citron}, starting it`);
  const started = spawnSync(
    "docker",
    ["compose", "-f", "docker-compose.yml", "-f", "docker-compose.sandbox.yml", "up", "-d", "citron"],
    { stdio: "inherit", shell: true, cwd: rootDir },
  );
  if (started.status !== 0) {
    console.warn("\n!!  Could not start the sandbox. Run and Submit will fail until it is up.\n");
    return;
  }

  // The container reports healthy well before it answers, so poll rather than assume.
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await isReachable(`${citron}/ready`)) {
      console.log("==> code sandbox ready");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  console.warn("\n!!  Sandbox started but never became ready. Run and Submit will fail.\n");
}

function runDev() {
  console.log(`==> starting agent (reload) on :${port}`);
  const agent = spawnLong(
    "uv",
    ["run", "python", "-m", "uvicorn", "app.main:app", "--reload", "--port", port],
    { cwd: agentDir },
  );

  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    agent.kill();
  };
  process.on("exit", cleanup);
  process.on("SIGINT", () => {
    cleanup();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    cleanup();
    process.exit(0);
  });

  console.log(`==> starting react-router dev server (proxies /api -> :${port})`);
  // Said plainly because getting this wrong is invisible: :8000 is the API only in dev,
  // and if a stale agent/static is lying around it will happily serve an old app there.
  console.log("==> OPEN THE VITE URL BELOW, not localhost:" + port);
  const web = spawnLong("pnpm", ["run", "dev:web"], {
    cwd: rootDir,
    env: { ...process.env, AGENT_URL: `http://localhost:${port}` },
  });
  web.on("exit", (code) => {
    cleanup();
    process.exit(code ?? 0);
  });
}

function runProd() {
  console.log("==> building frontend");
  runSync("pnpm", ["run", "build"], { cwd: rootDir });

  console.log("==> staging build into agent/static");
  const staticDir = path.join(agentDir, "static");
  rmSync(staticDir, { recursive: true, force: true });
  mkdirSync(staticDir, { recursive: true });
  cpSync(path.join(rootDir, "build", "client"), staticDir, { recursive: true });

  console.log(`==> starting agent on :${port}`);
  const agent = spawnLong(
    "uv",
    ["run", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port],
    { cwd: agentDir },
  );
  agent.on("exit", (code) => process.exit(code ?? 0));
}

if (mode === "dev") {
  await preflight();
  runDev();
} else if (mode === "prod") {
  runProd();
} else {
  console.error("usage: node scripts/run.js [dev|prod]");
  process.exit(1);
}
