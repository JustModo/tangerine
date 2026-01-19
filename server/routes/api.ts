import { Router } from "express";
import { detectLanguages } from "../services/language_service";
import { runCode } from "../services/runner_service";
import { watchFile } from "../services/watcher_service";
import { listDirectory, getParentDir, readFileContent } from "../services/fs_service";
import { z } from "zod";
import os from "os";

const router = Router();

// Languages Route
router.get("/languages", async (req, res) => {
    const languages = await detectLanguages();
    res.json(languages);
});

// FS Routes
router.get("/fs/list", async (req, res) => {
    try {
        const dirPath = (req.query.path as string) || process.cwd();
        const result = await listDirectory(dirPath);
        res.json({ ...result, parent: getParentDir(result.currentPath) });
    } catch (err: any) {
        res.status(500).json({ error: err.message });
    }
});

router.get("/fs/home", (req, res) => {
    res.json({ path: os.homedir() });
});

router.get("/fs/read", async (req, res) => {
    try {
        const filePath = req.query.path as string;
        if (!filePath) return res.status(400).json({ error: "Missing path" });
        const content = await readFileContent(filePath);
        res.json(content);
    } catch (err: any) {
        res.status(500).json({ error: err.message });
    }
});

// Watch File Route (SSE)
router.get("/watch", (req, res) => {
    const filePath = req.query.path as string;

    if (!filePath) {
        res.status(400).send("Missing path");
        return;
    }

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    const cleanup = watchFile(filePath,
        (content) => {
            res.write(`event: change\ndata: ${JSON.stringify({ content })}\n\n`);
        },
        (err) => {
            res.write(`event: error\ndata: ${JSON.stringify({ message: err.message })}\n\n`);
        }
    );

    req.on("close", () => {
        cleanup();
    });
});

// Run Route (SSE)
router.post("/run", async (req, res) => {
    const BodySchema = z.object({
        language: z.string(),
        codePath: z.string(), // Client sends local path. NOTE: For security this is usually bad, but for a LOCAL tool this is required by the prompt ("client calls express... imports file... imports on watch mode")
        testCases: z.array(z.object({
            id: z.string(),
            input: z.string(),
            output: z.string()
        }))
    });

    try {
        const body = BodySchema.parse(req.body);

        // Set up SSE
        res.setHeader("Content-Type", "text/event-stream");
        res.setHeader("Cache-Control", "no-cache");
        res.setHeader("Connection", "keep-alive");
        res.flushHeaders();

        await runCode(body.language, body.codePath, body.testCases, (result) => {
            res.write(`data: ${JSON.stringify(result)}\n\n`);
        });

        res.write(`event: done\ndata: {}\n\n`);
        res.end();

    } catch (error: any) {
        if (!res.headersSent) {
            res.status(400).json({ error: error.message || "Invalid request" });
        } else {
            res.write(`event: error\ndata: ${JSON.stringify({ message: error.message })}\n\n`);
            res.end();
        }
    }
});

export const apiRouter = router;
