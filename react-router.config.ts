import type { Config } from "@react-router/dev/config";

export default {
  // SPA mode: `react-router build` outputs a static build/client/ only (no server
  // bundle) — served by the Python agent (agent/app/main.py), not Node/Express.
  ssr: false,
} satisfies Config;
