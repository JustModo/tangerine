import { useState } from "react";
import type { MetaFunction } from "react-router";
import { useLoaderData, useNavigate } from "react-router";
import { Check } from "lucide-react";
import { CodeWorkbench } from "@/components/code-workbench/CodeWorkbench";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch, apiJson, consumeSSE } from "~/lib/api";
import type { AttemptMetrics, EvaluationResult, ProblemDetail, TestResult } from "~/lib/types";

interface ProblemSessionData {
  id: string;
  problem_id: string;
  lesson_node_id: string | null;
  lesson_plan_id: string | null;
  source_code: string | null;
  status: string;
  flagged: boolean;
}

export async function clientLoader({ params }: { params: { id?: string } }) {
  const session = await apiJson<ProblemSessionData>(`/api/problem-sessions/${params.id}`);
  const problem = await apiJson<ProblemDetail>(`/api/problems/${session.problem_id}`);
  return { session, problem };
}

export const meta: MetaFunction = () => [
  { title: "Problem · Tangerine" },
  { name: "description", content: "Solve the problem, run it against the examples, and submit for hidden tests." },
];

export default function ProblemSessionScreen() {
  const { session, problem } = useLoaderData<typeof clientLoader>();
  const id = session.id;
  const [solved, setSolved] = useState(session.status === "COMPLETED");
  const navigate = useNavigate();

  async function autosave(code: string) {
    try {
      await apiJson(`/api/problem-sessions/${id}/code`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_code: code }),
      });
    } catch {
      // Non-critical - a failed autosave tick just means the next one (or Run/Submit,
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

    // Buffered rather than yielded frame-by-frame: consumeSSE is callback-based, and the
    // sandbox returns every result in one response anyway, so nothing is lost - but an
    // error frame now reaches the caller instead of the stream just ending.
    const results: TestResult[] = [];
    await consumeSSE(response, (event) => results.push(event as unknown as TestResult));
    for (const result of results) yield result;
  }

  async function submitCode(code: string, metrics: AttemptMetrics): Promise<EvaluationResult> {
    return apiJson<EvaluationResult>(`/api/problem-sessions/${id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_code: code, metrics }),
    });
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <PageHeader
        title={problem.title}
        subtitle={`${problem.language} · ${problem.difficulty}`}
        actions={
          solved && session.lesson_plan_id ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate(`/plans/${session.lesson_plan_id}`)}
              >
                Back to plan
              </Button>
              <Check className="h-4 w-4 text-green-500" />
            </>
          ) : null
        }
      />
      <div className="flex-1 min-h-0">
        <CodeWorkbench
          problem={problem}
          initialCode={session.source_code ?? problem.user_code}
          onAutosave={autosave}
          onRun={runCode}
          onSubmit={submitCode}
          lessonNodeId={session.lesson_node_id ?? undefined}
          problemSessionId={session.id}
          initiallySolved={session.status === "COMPLETED"}
          initiallyFlagged={session.flagged}
          onSolved={() => setSolved(true)}
        />
      </div>
    </div>
  );
}
