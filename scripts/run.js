#!/usr/bin/env node
// Centralized dev/prod entrypoint — cross-platform (Windows/macOS/Linux), Node.js only
// (no bash), since `uv`/`pnpm` resolution across platforms needs a shell either way.
//   node scripts/run.js dev   — agent in --reload mode + the react-router dev server
//   node scripts/run.js prod  — builds the SPA, stages it into agent/static, runs the agent alone
import { spawn, spawnSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync } from "node:fs";
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
  runDev();
} else if (mode === "prod") {
  runProd();
} else {
  console.error("usage: node scripts/run.js [dev|prod]");
  process.exit(1);
}
