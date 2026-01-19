import fs from "fs/promises";
import path from "path";
import os from "os";

export interface FileInfo {
    name: string;
    path: string;
    isDirectory: boolean;
}

export async function listDirectory(dirPath: string): Promise<{ files: FileInfo[], currentPath: string }> {
    let absolutePath = dirPath || os.homedir();

    try {
        const stats = await fs.stat(absolutePath);
        if (!stats.isDirectory()) {
            absolutePath = path.dirname(absolutePath);
        }
    } catch (e) {
        // If path doesn't exist or error, fallback to home
        absolutePath = os.homedir();
    }

    try {
        const entries = await fs.readdir(absolutePath, { withFileTypes: true });

        const files = entries
            .filter(entry => !entry.name.startsWith('.'))
            .map(entry => ({
                name: entry.name,
                path: path.join(absolutePath, entry.name),
                isDirectory: entry.isDirectory()
            }))
            .sort((a, b) => {
                if (a.isDirectory === b.isDirectory) return a.name.localeCompare(b.name);
                return a.isDirectory ? -1 : 1;
            });

        return { files, currentPath: absolutePath };
    } catch (err: any) {
        // Fallback to home if current path is inaccessible
        if (absolutePath !== os.homedir()) {
            return listDirectory(os.homedir());
        }
        throw err;
    }
}

export function getParentDir(dirPath: string): string {
    return path.dirname(dirPath);
}

export async function readFileContent(filePath: string): Promise<any> {
    const content = await fs.readFile(filePath, "utf-8");
    return JSON.parse(content);
}
