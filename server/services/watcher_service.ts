import chokidar from "chokidar";
import fs from "fs/promises";

export function watchFile(filePath: string, onChange: (content: string) => void, onError: (err: any) => void) {
    const watcher = chokidar.watch(filePath, {
        persistent: true,
        usePolling: true, // often better for individual files across OSs
    });

    watcher
        .on("add", async () => {
            try {
                const content = await fs.readFile(filePath, "utf-8");
                onChange(content);
            } catch (e) { onError(e); }
        })
        .on("change", async () => {
            try {
                const content = await fs.readFile(filePath, "utf-8");
                onChange(content);
            } catch (e) { onError(e); }
        })
        .on("error", onError);

    return () => watcher.close();
}
