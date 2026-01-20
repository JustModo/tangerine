import { exec, spawn } from "child_process";
import { promisify } from "util";
import fs from "fs/promises";
import path from "path";
import os from "os";
import crypto from "crypto";
import { type ExecutionResult } from "../schemas/question_schema";

const execAsync = promisify(exec);

/**
 * Normalizes output by trimming whitespace and normalizing newlines.
 */
function normalizeOutput(output: string): string {
  return output.trim().replace(/\r\n/g, "\n");
}

/**
 * Hashes normalized output.
 */
function hashOutput(output: string): string {
  return crypto
    .createHash("sha256")
    .update(normalizeOutput(output))
    .digest("hex");
}

export async function runCode(
  languageId: string,
  codePath: string,
  testCases: { id: string; input: string; output: string }[],
  onProgress: (result: ExecutionResult) => void,
) {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "runner-"));

  try {
    let runCommand: string;
    let executablePath = codePath;

    // Compilation / Setup
    if (languageId === "c" || languageId === "cpp") {
      const compiledPath = path.join(tempDir, "out");
      const compiler = languageId === "c" ? "gcc" : "g++";
      try {
        await execAsync(`${compiler} "${codePath}" -o "${compiledPath}"`);
        executablePath = compiledPath;
        runCommand = `"${executablePath}"`;
      } catch (compileError: any) {
        // Fail all testcases if compilation fails
        testCases.forEach((tc) => {
          onProgress({
            id: tc.id,
            status: "ERROR",
            input: tc.input,
            expectedOutput: tc.output,
            error: `Compilation Error: ${compileError.message || compileError.stderr}`,
          });
        });
        return;
      }
    } else if (languageId === "python") {
      runCommand =
        process.platform === "win32"
          ? `py -3 -u "${codePath}"`
          : `python3 -u "${codePath}"`; // -u for unbuffered output
    } else if (languageId === "javascript") {
      runCommand = `node "${codePath}"`;
    } else if (languageId === "java") {
      // Java is tricky because of class names. Assuming single file with Main class or loose execution.
      // For simple single-file execution in newer Java versions (11+): java File.java works
      runCommand = `java "${codePath}"`;
    } else {
      throw new Error(`Unsupported language: ${languageId}`);
    }

    // Execution
    for (const testCase of testCases) {
      const result = await executeSingleTestCase(
        runCommand,
        testCase.input,
        tempDir,
      );

      let status: ExecutionResult["status"] = "PASSED";
      if (result.error) {
        status = "ERROR";
      } else if (result.isTimeout) {
        status = "TIMEOUT";
      } else {
        const actualHash = hashOutput(result.stdout || "");
        const expectedHash = testCase.output.trim(); // Stored as hash in JSON
        if (actualHash !== expectedHash) {
          status = "FAILED";
        }
      }

      onProgress({
        id: testCase.id,
        status,
        input: testCase.input,
        expectedOutput: testCase.output,
        actualOutput: result.stdout,
        error: result.stderr || result.error,
        executionTime: result.duration
          ? result.duration.toFixed(2) + "ms"
          : undefined,
      });
    }
  } catch (err: any) {
    console.error("Runner Error:", err);
    // Global error
    testCases.forEach((tc) => {
      onProgress({
        id: tc.id,
        status: "ERROR",
        input: tc.input,
        expectedOutput: tc.output,
        error: `Runner System Error: ${err.message}`,
      });
    });
  } finally {
    // Cleanup
    try {
      await fs.rm(tempDir, { recursive: true, force: true });
    } catch (e) {
      console.error("Failed to cleanup temp dir", e);
    }
  }
}

async function executeSingleTestCase(
  command: string,
  input: string,
  cwd: string,
): Promise<{
  stdout: string;
  stderr: string;
  error?: string;
  isTimeout?: boolean;
  duration?: number;
}> {
  return new Promise((resolve) => {
    const start = performance.now();
    const child = spawn(command, { shell: true, cwd });

    let stdout = "";
    let stderr = "";
    let isTimeout = false;

    // Timeout (e.g. 2 seconds)
    const timer = setTimeout(() => {
      isTimeout = true;
      child.kill();
      resolve({
        stdout,
        stderr,
        isTimeout: true,
        duration: performance.now() - start,
      });
    }, 5000); // 5 sec timeout default

    if (child.stdin) {
      child.stdin.write(input);
      child.stdin.end();
    }

    child.stdout?.on("data", (data) => {
      stdout += data.toString();
    });
    child.stderr?.on("data", (data) => {
      stderr += data.toString();
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      const duration = performance.now() - start;
      if (isTimeout) return; // already resolved

      if (code !== 0) {
        resolve({
          stdout,
          stderr,
          error: `Process exited with code ${code}`,
          duration,
        });
      } else {
        resolve({ stdout, stderr, duration });
      }
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({
        stdout,
        stderr,
        error: err.message,
        duration: performance.now() - start,
      });
    });
  });
}
