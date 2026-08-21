import { useEffect, useRef, useState } from "react";
import { Play, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Separator } from "@/components/ui/separator";
import { useStatus } from "~/lib/status";
import { ApiError } from "~/lib/api";
import type { EvaluationResult, ProblemDetail, TestResult } from "~/lib/types";
import { ProblemPanel } from "./ProblemPanel";
import { MonacoEditor } from "./MonacoEditor";
import { TestCasePanel, type TestPanelStatus } from "./TestCasePanel";

const AUTOSAVE_DELAY_MS = 2000;

interface CodeWorkbenchProps {
  problem: ProblemDetail;
  initialCode: string;
  onAutosave?: (code: string) => void;
  onRun: (code: string) => AsyncGenerator<TestResult>;
  onSubmit: ((code: string) => Promise<EvaluationResult>) | null;
}

export function CodeWorkbench({ problem, initialCode, onAutosave, onRun, onSubmit }: CodeWorkbenchProps) {
  const [code, setCode] = useState(initialCode);
  const [isRunning, setIsRunning] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [panelStatus, setPanelStatus] = useState<TestPanelStatus>("idle");
  const [panelLabel, setPanelLabel] = useState("");
  const [panelResults, setPanelResults] = useState<TestResult[]>([]);
  const [panelHidden, setPanelHidden] = useState(false);
  const [summary, setSummary] = useState<{ passed: number; total: number; feedback?: string | null } | null>(
    null,
  );
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const { showError } = useStatus();

  useEffect(() => {
    if (!onAutosave) return;
    clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => onAutosave(code), AUTOSAVE_DELAY_MS);
    return () => clearTimeout(autosaveTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  async function handleRun() {
    setIsRunning(true);
    setPanelStatus("running");
    setPanelResults([]);
    setPanelHidden(false);
    setSummary(null);
    setPanelLabel("Queued...");
    try {
      let first = true;
      for await (const result of onRun(code)) {
        if (first) {
          setPanelLabel("Executing...");
          first = false;
        }
        setPanelResults((prev) => [...prev, result]);
      }
      setPanelStatus("done");
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Run failed");
      setPanelStatus("idle");
    } finally {
      setIsRunning(false);
    }
  }

  async function handleSubmit() {
    if (!onSubmit) return;
    setIsSubmitting(true);
    setPanelStatus("running");
    setPanelResults([]);
    setPanelHidden(true);
    setSummary(null);
    setPanelLabel("Evaluating...");
    try {
      const evaluation = await onSubmit(code);
      setPanelResults(evaluation.results);
      setSummary({ passed: evaluation.passed_tests, total: evaluation.total_tests, feedback: evaluation.feedback });
      setPanelStatus("done");
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Submission failed");
      setPanelStatus("idle");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-black text-white">
      <ResizablePanelGroup direction="horizontal" className="flex-1 min-h-0">
        <ResizablePanel defaultSize={32} minSize={20}>
          <ProblemPanel problem={problem} />
        </ResizablePanel>
        <ResizableHandle className="w-1 bg-white/5" />
        <ResizablePanel defaultSize={68} minSize={30}>
          <ResizablePanelGroup direction="vertical" className="h-full">
            <ResizablePanel defaultSize={55} minSize={15} className="flex flex-col">
              <div className="flex-none h-11 bg-zinc-950 border-b border-white/10 flex items-center justify-between px-4">
                <span className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
                  Editor
                </span>
              </div>
              <div className="flex-1 min-h-0">
                <MonacoEditor language={problem.language} value={code} onChange={setCode} />
              </div>
            </ResizablePanel>
            <ResizableHandle className="h-1 bg-white/5" />
            <ResizablePanel defaultSize={45} minSize={15} className="flex flex-col">
              <div className="flex-none h-11 bg-zinc-950 border-b border-white/10 flex items-center justify-between px-4">
                <span className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
                  Test Cases
                </span>
                <div className="flex items-center gap-2">
                  <Button variant="secondary" size="sm" onClick={handleRun} disabled={isRunning || isSubmitting}>
                    {isRunning ? (
                      <RefreshCcw className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-3.5 w-3.5" />
                    )}
                    {isRunning ? "Running..." : "Run"}
                  </Button>
                  {onSubmit && (
                    <Button size="sm" onClick={handleSubmit} disabled={isRunning || isSubmitting}>
                      {isSubmitting ? (
                        <RefreshCcw className="mr-2 h-3.5 w-3.5 animate-spin" />
                      ) : null}
                      {isSubmitting ? "Submitting..." : "Submit"}
                    </Button>
                  )}
                </div>
              </div>
              <Separator className="bg-white/10" />
              <div className="flex-1 min-h-0">
                <TestCasePanel
                  status={panelStatus}
                  runningLabel={panelLabel}
                  results={panelResults}
                  hidden={panelHidden}
                  summary={summary}
                />
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
