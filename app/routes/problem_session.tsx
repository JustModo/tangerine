import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { toast } from "sonner";
import { ChevronLeft, FileCode, Folder, Play, RefreshCcw, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "~/lib/utils";

interface ProblemSessionData {
  id: string;
  problem_id: string;
  code_path: string | null;
  status: string;
}

interface ProblemExample {
  id: string;
  input: string;
  output: string;
  explanation?: string | null;
}

interface ProblemDetail {
  id: string;
  title: string;
  language: string;
  difficulty: string;
  statement_md: string;
  boilerplate: string;
  examples: ProblemExample[];
}

interface RunResult {
  id: string;
  status: string;
  input: string;
  actual_output?: string | null;
  error?: string | null;
  execution_time_ms?: string | null;
}

interface EvaluationResult {
  passed_tests: number;
  total_tests: number;
  feedback?: string | null;
}

export default function ProblemSessionScreen() {
  const { id } = useParams();
  const [session, setSession] = useState<ProblemSessionData | null>(null);
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [codePath, setCodePath] = useState("");
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [isRunning, setIsRunning] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);

  const [showPicker, setShowPicker] = useState(false);
  const [explorerPath, setExplorerPath] = useState("");
  const [explorerFiles, setExplorerFiles] = useState<any[]>([]);

  async function load() {
    const sessionRes = await fetch(`/api/problem-sessions/${id}`);
    if (!sessionRes.ok) {
      toast.error("Problem session not found");
      return;
    }
    const sessionData = await sessionRes.json();
    setSession(sessionData);
    setCodePath(sessionData.code_path || "");

    const problemRes = await fetch(`/api/problems/${sessionData.problem_id}`);
    if (problemRes.ok) setProblem(await problemRes.json());
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const openPicker = async (path?: string) => {
    try {
      const resp = await fetch(`/api/workspace/list${path ? `?path=${encodeURIComponent(path)}` : ""}`);
      const data = await resp.json();
      setExplorerPath(data.current_path);
      setExplorerFiles(data.files);
      setShowPicker(true);
    } catch {
      toast.error("PICKER ERROR");
    }
  };

  async function selectSourceFile(path: string) {
    setCodePath(path);
    setShowPicker(false);
    await fetch(`/api/problem-sessions/${id}/source`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code_path: path }),
    });
  }

  async function runVisibleTests() {
    if (!codePath) return;
    setIsRunning(true);
    setResults({});
    try {
      const response = await fetch(`/api/problem-sessions/${id}/run`, {
        method: "POST",
      });
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          for (const line of chunk.split("\n\n")) {
            if (!line.startsWith("data: ")) continue;
            const dataStr = line.replace("data: ", "");
            if (dataStr === "{}" || !dataStr.trim()) continue;
            try {
              const result = JSON.parse(dataStr) as RunResult;
              setResults((prev) => ({ ...prev, [result.id]: result }));
            } catch {}
          }
        }
      }
    } catch {
      toast.error("Run failed");
    } finally {
      setIsRunning(false);
    }
  }

  async function submit() {
    if (!codePath) return;
    setIsSubmitting(true);
    try {
      const res = await fetch(`/api/problem-sessions/${id}/submit`, { method: "POST" });
      if (!res.ok) {
        toast.error("Submission failed");
        return;
      }
      const evaluationData = await res.json();
      setEvaluation(evaluationData);
      toast.success(
        evaluationData.passed_tests === evaluationData.total_tests
          ? "All hidden tests passed!"
          : `${evaluationData.passed_tests}/${evaluationData.total_tests} hidden tests passed`,
      );
    } catch {
      toast.error("Submission failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!session || !problem) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500 text-xs uppercase tracking-widest">
        Loading problem...
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-black text-white px-10 pt-10">
      <div className="flex-none">
        <div className="flex items-center justify-between mb-8">
          <div className="space-y-1">
            <h1 className="text-4xl font-black tracking-tighter uppercase">{problem.title}</h1>
            <p className="text-zinc-500 text-xs font-bold uppercase tracking-[0.2em]">
              {problem.language} · {problem.difficulty}
            </p>
          </div>
        </div>

        <div className="flex gap-4 mb-8">
          <div className="flex-1 flex gap-2">
            <Input
              placeholder="FULL PATH TO SOURCE FILE"
              className="flex-1 bg-zinc-950 border-white/10 font-bold uppercase tracking-widest text-[10px]"
              value={codePath}
              onChange={(e) => setCodePath(e.target.value)}
              onBlur={() => codePath && selectSourceFile(codePath)}
            />
            <Button
              variant="outline"
              className="border-dashed border-white/20 hover:border-white text-[10px]"
              onClick={() => openPicker()}
            >
              PICK SOURCE
            </Button>
          </div>
          <Button
            onClick={runVisibleTests}
            disabled={!codePath || isRunning}
            variant="outline"
            className="text-[10px]"
          >
            {isRunning ? (
              <RefreshCcw className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            RUN
          </Button>
          <Button onClick={submit} disabled={!codePath || isSubmitting} className="text-[10px]">
            SUBMIT
          </Button>
        </div>
        <Separator className="bg-white/10 mb-8" />
      </div>

      <ResizablePanelGroup direction="horizontal" className="flex-1 min-h-0 overflow-hidden">
        <ResizablePanel defaultSize={40}>
          <ScrollArea className="h-full p-8 prose dark:prose-invert max-w-none bg-zinc-950 border-r border-white/10">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.statement_md}</ReactMarkdown>
            {problem.boilerplate && (
              <>
                <h3>Boilerplate</h3>
                <pre className="text-xs whitespace-pre-wrap">{problem.boilerplate}</pre>
              </>
            )}
          </ScrollArea>
        </ResizablePanel>

        <ResizableHandle className="w-1 bg-white/5" />

        <ResizablePanel defaultSize={60} className="h-full overflow-hidden">
          <div className="h-full flex flex-col bg-black overflow-hidden">
            <ScrollArea className="flex-1 min-h-0 px-8 py-8 w-full">
              <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 mb-4">
                Visible Example Results
              </h3>
              <div className="space-y-3">
                {problem.examples.map((example) => {
                  const result = results[example.id];
                  return (
                    <div
                      key={example.id}
                      className="border border-white/10 p-4 text-xs font-mono space-y-1"
                    >
                      <div>
                        <span className="text-zinc-600">IN:</span> {example.input}
                      </div>
                      <div>
                        <span className="text-zinc-600">STATUS:</span>{" "}
                        <span
                          className={cn(
                            "font-black",
                            result?.status === "PASSED" && "text-green-500",
                            result?.status === "FAILED" && "text-red-500",
                          )}
                        >
                          {result?.status || "PENDING"}
                        </span>
                      </div>
                      {result?.actual_output && (
                        <div className="text-zinc-500">OUT: {result.actual_output}</div>
                      )}
                    </div>
                  );
                })}
              </div>

              {evaluation && (
                <div className="mt-8 border-t border-white/10 pt-6 space-y-2">
                  <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
                    Evaluation
                  </h3>
                  <p className="text-sm font-bold">
                    {evaluation.passed_tests} / {evaluation.total_tests} hidden tests passed
                  </p>
                  {evaluation.feedback && (
                    <p className="text-xs text-zinc-400">{evaluation.feedback}</p>
                  )}
                </div>
              )}
            </ScrollArea>
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      {showPicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-2xl bg-zinc-950 border border-white/20 flex flex-col h-[70vh] overflow-hidden">
            <div className="flex-none p-6 border-b border-white/10 flex justify-between items-center bg-black">
              <div className="space-y-1">
                <h3 className="text-sm font-black uppercase tracking-widest">
                  Select Source File
                </h3>
                <p className="text-[9px] font-mono text-zinc-500 overflow-hidden text-ellipsis whitespace-nowrap max-w-md">
                  {explorerPath}
                </p>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setShowPicker(false)}>
                <X className="w-4 h-4" />
              </Button>
            </div>

            <div className="flex-none p-4 flex gap-2 overflow-x-auto bg-zinc-900 border-b border-white/5">
              <Button
                variant="ghost"
                size="sm"
                className="text-[9px] font-black uppercase"
                onClick={() =>
                  openPicker(explorerPath.split("/").slice(0, -1).join("/") || "/")
                }
              >
                <ChevronLeft className="w-3 h-3 mr-2" /> UP
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-[9px] font-black uppercase"
                onClick={async () => {
                  const resp = await fetch("/api/workspace/home");
                  const data = await resp.json();
                  openPicker(data.path);
                }}
              >
                HOME
              </Button>
            </div>

            <div className="flex-1 overflow-hidden">
              <ScrollArea className="h-full w-full">
                <div className="p-2">
                  {explorerFiles.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() =>
                        file.is_directory ? openPicker(file.path) : selectSourceFile(file.path)
                      }
                      className="w-full flex items-center gap-3 p-3 text-[11px] font-medium border border-transparent hover:border-white/10 hover:bg-white/5 transition-all text-left group"
                    >
                      {file.is_directory ? (
                        <Folder className="w-4 h-4 text-zinc-500 group-hover:text-white" />
                      ) : (
                        <FileCode className="w-4 h-4 text-white" />
                      )}
                      <span
                        className={cn(
                          file.is_directory ? "text-zinc-400" : "text-white",
                          "group-hover:text-white",
                        )}
                      >
                        {file.name}
                      </span>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
