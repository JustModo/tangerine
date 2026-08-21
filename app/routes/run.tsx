import { useState } from "react";
import { toast } from "sonner";
import { FolderOpen, Hash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CodeWorkbench } from "@/components/code-workbench/CodeWorkbench";
import { useStatus } from "~/lib/status";
import { ApiError, apiFetch } from "~/lib/api";
import type { ProblemDetail, TestResult } from "~/lib/types";

interface TestCaseSpec {
  id?: string;
  input: string;
  output: string; // stored as a sha256 hash, never plaintext
}

interface QuestionExport {
  title: string;
  description: string;
  languages: string[];
  testCases: TestCaseSpec[];
}

function toProblem(question: QuestionExport, language: string): ProblemDetail {
  return {
    id: "practice",
    title: question.title,
    language,
    difficulty: "practice",
    statement_md: question.description,
    boilerplate: "",
    constraints: null,
    hints: [],
    tags: [],
    examples: question.testCases.map((tc, index) => ({
      id: tc.id || String(index),
      input: tc.input,
      output: "",
    })),
  };
}

export default function Runner() {
  const [question, setQuestion] = useState<QuestionExport | null>(null);
  const [language, setLanguage] = useState<string>("");
  const { showError } = useStatus();

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const json = JSON.parse(event.target?.result as string);
        if (!json.title || !json.testCases) throw new Error("INVALID");
        setQuestion(json);
        setLanguage(json.languages?.[0] || "");
        toast.success("QUESTION LOADED");
      } catch {
        showError("Failed to parse question file");
      }
    };
    reader.readAsText(file);
  };

  async function* runCode(code: string): AsyncGenerator<TestResult> {
    if (!question) return;
    const response = await apiFetch("/api/execution/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language,
        code,
        test_cases: question.testCases.map((tc, index) => ({
          id: tc.id || String(index),
          input: tc.input,
          output_hash: tc.output,
        })),
      }),
    });
    if (!response.ok) throw new ApiError(`Run failed (${response.status})`, response.status);

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) return;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      for (const line of chunk.split("\n\n")) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.replace("data: ", "");
        if (dataStr === "{}" || !dataStr.trim()) continue;
        try {
          yield JSON.parse(dataStr) as TestResult;
        } catch {}
      }
    }
  }

  if (!question) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-6 bg-black text-white">
        <div className="flex flex-col items-center gap-4 opacity-40">
          <Hash className="w-12 h-12" />
          <span className="text-[10px] font-black uppercase tracking-[0.5em]">System Idle</span>
        </div>
        <div className="relative group">
          <input
            type="file"
            accept=".json"
            className="absolute inset-0 opacity-0 cursor-pointer"
            onChange={handleFileUpload}
          />
          <Button variant="outline" size="sm" className="h-10 text-[10px]">
            <FolderOpen className="mr-2 h-4 w-4" /> OPEN JSON
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0">
      <CodeWorkbench
        problem={toProblem(question, language)}
        initialCode=""
        onRun={runCode}
        onSubmit={null}
      />
    </div>
  );
}
