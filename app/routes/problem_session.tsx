import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { CodeWorkbench } from "@/components/code-workbench/CodeWorkbench";
import { PageHeader } from "@/components/PageHeader";
import { useStatus } from "~/lib/status";
import { ApiError, apiFetch, apiJson } from "~/lib/api";
import type { EvaluationResult, ProblemDetail, TestResult } from "~/lib/types";

interface ProblemSessionData {
  id: string;
  problem_id: string;
  lesson_node_id: string;
  lesson_plan_id: string | null;
  source_code: string | null;
  status: string;
}

export default function ProblemSessionScreen() {
  const { id } = useParams();
  const [session, setSession] = useState<ProblemSessionData | null>(null);
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const { showError } = useStatus();

  async function load() {
    try {
      const sessionData = await apiJson<ProblemSessionData>(`/api/problem-sessions/${id}`);
      setSession(sessionData);
      setProblem(await apiJson<ProblemDetail>(`/api/problems/${sessionData.problem_id}`));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load problem session");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function autosave(code: string) {
    try {
      await apiJson(`/api/problem-sessions/${id}/code`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_code: code }),
      });
    } catch {
      // Non-critical — a failed autosave tick just means the next one (or Run/Submit,
      // which also save) will catch it up. Not worth interrupting the user for.
    }
  }

  async function* runCode(code: string): AsyncGenerator<TestResult> {
    const response = await apiFetch(`/api/problem-sessions/${id}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_code: code }),
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

  async function submitCode(code: string): Promise<EvaluationResult> {
    return apiJson<EvaluationResult>(`/api/problem-sessions/${id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_code: code }),
    });
  }

  if (!session || !problem) return null;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <PageHeader
        title={problem.title}
        subtitle={`${problem.language} · ${problem.difficulty}`}
        backTo={session.lesson_plan_id ? `/plans/${session.lesson_plan_id}` : undefined}
      />
      <div className="flex-1 min-h-0">
        <CodeWorkbench
          problem={problem}
          initialCode={session.source_code ?? problem.user_code}
          onAutosave={autosave}
          onRun={runCode}
          onSubmit={submitCode}
          lessonNodeId={session.lesson_node_id}
          problemSessionId={session.id}
        />
      </div>
    </div>
  );
}
