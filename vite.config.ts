import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";

// SPA mode (react-router.config.ts: ssr: false) — no server build target, just the
// client bundle. In dev, the agent's fetch calls need a live backend to talk to; point
// AGENT_URL at wherever `uvicorn app.main:app` is running.
export default defineConfig({
  server: {
    proxy: {
      "/api": process.env.AGENT_URL || "http://localhost:8000",
    },
  },
  plugins: [tailwindcss(), reactRouter(), tsconfigPaths()],
});