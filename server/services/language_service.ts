import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

export type LanguageInfo = {
    id: string;
    name: string;
    version: string | null;
    installed: boolean;
    runCommandTemplate: string; // Template for running, e.g., "python3 {file}"
    compileCommandTemplate?: string; // Optional compile command
};

const SUPPORTED_LANGUAGES: Record<string, Omit<LanguageInfo, "version" | "installed">> = {
    javascript: {
        id: "javascript",
        name: "JavaScript (Node.js)",
        runCommandTemplate: "node {file}",
    },
    python: {
        id: "python",
        name: "Python 3",
        runCommandTemplate: "python3 {file}", // simplified, might need checks
    },
    c: {
        id: "c",
        name: "C",
        compileCommandTemplate: "gcc {file} -o {output}",
        runCommandTemplate: "{file}",
    },
    bg_cpp: {
        id: "bg_cpp",
        name: "C++",
        compileCommandTemplate: "g++ {file} -o {output}",
        runCommandTemplate: "{file}",
    },
    java: {
        id: "java",
        name: "Java",
        compileCommandTemplate: "javac {file}",
        runCommandTemplate: "java {file}", // Simplified, requires class name parsing potentially
    }
};

export async function detectLanguages(): Promise<LanguageInfo[]> {
    const results: LanguageInfo[] = [];

    // Node.js
    try {
        const { stdout } = await execAsync("node --version");
        results.push({ ...SUPPORTED_LANGUAGES.javascript, version: stdout.trim(), installed: true });
    } catch {
        results.push({ ...SUPPORTED_LANGUAGES.javascript, version: null, installed: false });
    }

    // Python
    try {
        const { stdout } = await execAsync("python3 --version");
        results.push({ ...SUPPORTED_LANGUAGES.python, version: stdout.trim(), installed: true });
    } catch {
        try {
            const { stdout } = await execAsync("python --version");
            results.push({ ...SUPPORTED_LANGUAGES.python, version: stdout.trim(), installed: true });
        } catch {
            results.push({ ...SUPPORTED_LANGUAGES.python, version: null, installed: false });
        }
    }

    // GCC (C)
    try {
        const { stdout } = await execAsync("gcc --version");
        // unexpected output might occur, just take first line
        const version = stdout.split('\n')[0];
        results.push({ ...SUPPORTED_LANGUAGES.c, version: version, installed: true });
    } catch {
        results.push({ ...SUPPORTED_LANGUAGES.c, version: null, installed: false });
    }

    // G++ (C++)
    try {
        const { stdout } = await execAsync("g++ --version");
        // unexpected output might occur, just take first line
        const version = stdout.split('\n')[0];
        results.push({ ...SUPPORTED_LANGUAGES.bg_cpp, version: version, installed: true });
    } catch {
        results.push({ ...SUPPORTED_LANGUAGES.bg_cpp, version: null, installed: false });
    }

    // Java
    try {
        const { stdout, stderr } = await execAsync("java -version");
        // java -version often writes to stderr
        const output = stdout || stderr;
        const version = output.split('\n')[0];
        results.push({ ...SUPPORTED_LANGUAGES.java, version: version, installed: true });
    } catch {
        results.push({ ...SUPPORTED_LANGUAGES.java, version: null, installed: false });
    }

    return results;
}
