import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Play, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Separator } from "@/components/ui/separator";
import { useStatus } from "~/lib/status";
import { ApiError } from "~/lib/api";
import type {
  AttemptMetrics,
  EvaluationResult,
  HelperContext,
  ProblemDetail,
  TestResult,
} from "~/lib/types";
import { ProblemPanel } from "./ProblemPanel";
import { MonacoEditor } from "./MonacoEditor";
import { TestCasePanel, type TestPanelStatus } from "./TestCasePanel";
import { SectionLabel } from "@/components/Section";

const AUTOSAVE_DELAY_MS = 2000;

interface CodeWorkbenchProps {
  problem: ProblemDetail;
  initialCode: string;
  onAutosave?: (code: string) => void;
  onRun: (code: string) => AsyncGenerator<TestResult>;
  onSubmit: ((code: string, metrics: AttemptMetrics) => Promise<EvaluationResult>) | null;
  /** Enable the Notes and Helper tabs. Both absent in practice mode, which has neither a
   * lesson node nor a persisted problem session. */
  lessonNodeId?: string;
  problemSessionId?: string;
  /** True when the session was already passing before this page load - otherwise
   * revisiting a solved problem would hide the solution it had already earned. */
  initiallySolved?: boolean;
  /** The session's actual flagged state on load - otherwise the flag button always starts
   * unlit even for a problem you already flagged last time you opened it. */
  initiallyFlagged?: boolean;
}

export function CodeWorkbench({
  problem,
  initialCode,
  onAutosave,
  onRun,
  onSubmit,
  lessonNodeId,
  problemSessionId,
  initiallySolved = false,
  initiallyFlagged = false,
}: CodeWorkbenchProps) {
  const [code, setCode] = useState(initialCode);
  const [isRunning, setIsRunning] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [panelStatus, setPanelStatus] = useState<TestPanelStatus>("idle");
  const [panelLabel, setPanelLabel] = useState("");
  const [panelResults, setPanelResults] = useState<TestResult[]>([]);
  const [panelHidden, setPanelHidden] = useState(false);
  const [summary, setSummary] = useState<{ passed: number; total: number } | null>(null);
  const [verdict, setVerdict] = useState<EvaluationResult["complexity_verdict"]>(null);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // The helper chat reads these through a stable getter instead of props - passing `code`
  // down directly would re-render the chat (and its markdown) on every keystroke.
  const codeRef = useRef(code);
  codeRef.current = code;
  const lastRunRef = useRef<HelperContext["last_run"]>(null);
  const getHelperContext = useCallback<() => HelperContext>(
    () => ({ source_code: codeRef.current, last_run: lastRunRef.current }),
    [],
  );
  // What the attempt cost. Refs, not state: none of it should re-render anything, and all
  // of it is read once, at submit. The server has no way to observe any of it.
  const startedAtRef = useRef(Date.now());
  const runCountRef = useRef(0);
  const hintsUsedRef = useRef(0);
  const helperUsedRef = useRef(false);
  const onHintRevealed = useCallback((count: number) => {
    hintsUsedRef.current = count;
  }, []);
  const onHelperUsed = useCallback(() => {
    helperUsedRef.current = true;
  }, []);
  const { showError } = useStatus();
  const expectedById = useMemo(
    () => Object.fromEntries(problem.examples.map((example) => [example.id, example.output])),
    [problem.examples],
  );

  useEffect(() => {
    if (!onAutosave) return;
    clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => onAutosave(code), AUTOSAVE_DELAY_MS);
    return () => clearTimeout(autosaveTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  async function handleRun() {
    runCountRef.current += 1;
    setIsRunning(true);
    setPanelStatus("running");
    setPanelResults([]);
    setPanelHidden(false);
    setSummary(null);
    setPanelLabel("Queued...");
    try {
      let first = true;
      const collected: TestResult[] = [];
      for await (const result of onRun(code)) {
        if (first) {
          setPanelLabel("Executing...");
          first = false;
        }
        setPanelResults((prev) => [...prev, result]);
        collected.push(result);
      }
      lastRunRef.current = {
        kind: "run",
        passed: collected.filter((r) => r.status === "PASSED").length,
        total: collected.length,
        results: collected,
      };
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
    setVerdict(null);
    setPanelLabel("Evaluating...");
    try {
      const evaluation = await onSubmit(code, {
        duration_ms: Date.now() - startedAtRef.current,
        run_count: runCountRef.current,
        hints_used: hintsUsedRef.current,
        helper_used: helperUsedRef.current,
      });
      setPanelResults(evaluation.results);
      setSummary({ passed: evaluation.passed_tests, total: evaluation.total_tests });
      setVerdict(evaluation.complexity_verdict ?? null);
      lastRunRef.current = {
        kind: "submit",
        passed: evaluation.passed_tests,
        total: evaluation.total_tests,
        results: evaluation.results,
      };
      setPanelStatus("done");
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Submission failed");
      setPanelStatus("idle");
    } finally {
      setIsSubmitting(false);
    }
  }

  const shortcutRef = useRef<(event: KeyboardEvent) => void>(() => {});
  shortcutRef.current = (event: KeyboardEvent) => {
    if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey) return;

    const isRun = event.code === "Backquote";
    const isSubmit = event.key === "Enter";
    if (!isRun && !isSubmit) return;
    event.preventDefault();
    if (isRunning || isSubmitting) return;
    if (isRun) handleRun();
    else if (onSubmit) handleSubmit();
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => shortcutRef.current(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="h-full flex flex-col overflow-hidden bg-black text-white">
      <ResizablePanelGroup direction="horizontal" className="flex-1 min-h-0">
        <ResizablePanel defaultSize={32} minSize={20}>
          <ProblemPanel
            problem={problem}
            lessonNodeId={lessonNodeId}
            problemSessionId={problemSessionId}
            getContext={getHelperContext}
            onHintRevealed={onHintRevealed}
            onHelperUsed={onHelperUsed}
            solved={initiallySolved || (summary !== null && summary.passed === summary.total)}
            initiallyFlagged={initiallyFlagged}
          />
        </ResizablePanel>
        <ResizableHandle className="w-1 bg-white/5" />
        <ResizablePanel defaultSize={68} minSize={30}>
          <ResizablePanelGroup direction="vertical" className="h-full">
            <ResizablePanel defaultSize={55} minSize={15} className="flex flex-col">
              <div className="flex-none h-11 bg-zinc-950 border-b border-white/10 flex items-center justify-between px-4">
                <SectionLabel>
                  Editor
                </SectionLabel>
              </div>
              <div className="flex-1 min-h-0">
                <MonacoEditor language={problem.language} value={code} onChange={setCode} />
              </div>
            </ResizablePanel>
            <ResizableHandle className="h-1 bg-white/5" />
            <ResizablePanel defaultSize={45} minSize={15} className="flex flex-col">
              <div className="flex-none h-11 bg-zinc-950 border-b border-white/10 flex items-center justify-between px-4">
                <SectionLabel>
                  Test Cases
                </SectionLabel>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleRun}
                    disabled={isRunning || isSubmitting}
                    title="Ctrl/Cmd + `"
                  >
                    {isRunning ? (
                      <RefreshCcw className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-3.5 w-3.5" />
                    )}
                    {isRunning ? "Running..." : "Run"}
                  </Button>
                  {onSubmit && (
                    <Button
                      size="sm"
                      onClick={handleSubmit}
                      disabled={isRunning || isSubmitting}
                      title="Ctrl/Cmd + Enter"
                    >
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
                  expectedById={panelHidden ? undefined : expectedById}
                  summary={summary}
                  complexityVerdict={verdict}
                />
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
