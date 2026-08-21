import { Router, type Request, type Response } from "express";

const AGENT_URL = process.env.AGENT_URL || "http://localhost:8000";

const router = Router();

/**
 * Thin BFF proxy to the Python agent — no business logic here. Request/response
 * validation is the agent's job (Pydantic is the source of truth); duplicating it
 * here in zod would just be two schemas to keep in sync (plan.md's routing/proxy role).
 */
async function proxyJson(req: Request, res: Response, agentPath: string, method: string) {
    try {
        const response = await fetch(`${AGENT_URL}${agentPath}`, {
            method,
            headers: { "Content-Type": "application/json" },
            body: method === "GET" ? undefined : JSON.stringify(req.body ?? {}),
        });
        // FastAPI's default unhandled-exception handler returns a plain-text body, not
        // JSON — don't let that surface as a misleading "agent unreachable" error.
        const text = await response.text();
        let data: unknown;
        try {
            data = text ? JSON.parse(text) : null;
        } catch {
            data = { error: text || "Agent returned an empty response" };
        }
        res.status(response.status).json(data);
    } catch (err: any) {
        res.status(502).json({ error: `Agent unreachable: ${err.message}` });
    }
}

/** Same proxy role as proxyJson, but for the agent's SSE (streaming) endpoints. */
async function proxyStream(req: Request, res: Response, agentPath: string) {
    try {
        const response = await fetch(`${AGENT_URL}${agentPath}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(req.body ?? {}),
        });
        res.setHeader("Content-Type", "text/event-stream");
        res.setHeader("Cache-Control", "no-cache");
        res.setHeader("Connection", "keep-alive");
        res.flushHeaders();
        if (!response.body) {
            res.end();
            return;
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            res.write(decoder.decode(value));
        }
        res.end();
    } catch (err: any) {
        res.write(`event: error\ndata: ${JSON.stringify({ message: err.message })}\n\n`);
        res.end();
    }
}

router.post("/sessions", (req, res) => proxyJson(req, res, "/sessions", "POST"));
router.get("/sessions", (req, res) => proxyJson(req, res, "/sessions", "GET"));
router.get("/sessions/:id", (req, res) => proxyJson(req, res, `/sessions/${req.params.id}`, "GET"));
router.post("/sessions/:id/messages", (req, res) =>
    proxyJson(req, res, `/sessions/${req.params.id}/messages`, "POST"),
);

router.post("/plans", (req, res) => proxyJson(req, res, "/learning-plans", "POST"));
router.get("/plans/:id", (req, res) => proxyJson(req, res, `/learning-plans/${req.params.id}`, "GET"));
router.post("/plans/:id/accept", (req, res) =>
    proxyJson(req, res, `/learning-plans/${req.params.id}/accept`, "POST"),
);

router.post("/plans/:id/problems/next", (req, res) =>
    proxyJson(req, res, `/learning-plans/${req.params.id}/problems/next`, "POST"),
);

router.post("/problems/generate", (req, res) => proxyJson(req, res, "/problems/generate", "POST"));
router.get("/problems/:id", (req, res) => proxyJson(req, res, `/problems/${req.params.id}`, "GET"));

router.post("/evaluations", (req, res) => proxyJson(req, res, "/evaluations", "POST"));

router.get("/problem-sessions/:id", (req, res) =>
    proxyJson(req, res, `/problem-sessions/${req.params.id}`, "GET"),
);
router.post("/problem-sessions/:id/source", (req, res) =>
    proxyJson(req, res, `/problem-sessions/${req.params.id}/source`, "POST"),
);
router.post("/problem-sessions/:id/run", (req, res) =>
    proxyStream(req, res, `/problem-sessions/${req.params.id}/run`),
);
router.post("/problem-sessions/:id/submit", (req, res) =>
    proxyJson(req, res, `/problem-sessions/${req.params.id}/submit`, "POST"),
);

router.get("/users/:id/mastery", (req, res) =>
    proxyJson(req, res, `/users/${req.params.id}/mastery`, "GET"),
);
router.get("/users/:id/revision-queue", (req, res) =>
    proxyJson(req, res, `/users/${req.params.id}/revision-queue`, "GET"),
);

export const learningRouter = router;
