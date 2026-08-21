import { useEffect, useState } from "react";
import { CheckCircle2, EyeOff, Loader2, MessageCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "~/lib/utils";
import type { TestResult } from "~/lib/types";

export type TestPanelStatus = "idle" | "running" | "done";

interface TestCasePanelProps {
  status: TestPanelStatus;
  runningLabel: string;
  results: TestResult[];
  hidden: boolean;
  /** Real expected output per test id — only meaningful (and only ever passed) for
   * visible-example runs. Hidden/graded tests never have their expected value sent to
   * the client at all, so this stays empty for those. */
  expectedById?: Record<string, string>;
  summary?: { passed: number; total: number; feedback?: string | null } | null;
  /** Coaching feedback is generated on demand, not automatically on every submit — set
   * only when a summary is present and feedback hasn't been fetched yet. */
  onRequestFeedback?: () => void;
  feedbackLoading?: boolean;
}

export function TestCasePanel({
  status,
  runningLabel,
  results,
  hidden,
  expectedById,
  summary,
  onRequestFeedback,
  feedbackLoading,
}: TestCasePanelProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (results.length > 0 && !results.some((r) => r.id === selectedId)) {
      setSelectedId(results[0].id);
    }
  }, [results, selectedId]);

  if (status === "idle") {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-zinc-600">
        <EyeOff className="w-8 h-8" />
        <p className="text-xs font-bold uppercase tracking-widest">
          You haven't run your code yet.
        </p>
      </div>
    );
  }

  if (status === "running" && results.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-zinc-400">
        <Loader2 className="w-6 h-6 animate-spin" />
        <p className="text-xs font-bold uppercase tracking-widest">{runningLabel}</p>
      </div>
    );
  }

  const selected = results.find((r) => r.id === selectedId) ?? results[0] ?? null;

  return (
    <ScrollArea className="h-full">
      <div className="p-6 space-y-5">
        {summary && (
          <div className="flex items-center justify-between border border-white/10 bg-white/5 rounded-md px-4 py-2 text-sm">
            <span className="font-bold uppercase tracking-widest text-[10px] text-zinc-500">Score</span>
            <span className="font-black">
              {summary.passed} / {summary.total}
            </span>
          </div>
        )}
        <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(6.5rem, 1fr))" }}>
          {results.map((result, index) => {
            const passed = result.status === "PASSED";
            const active = result.id === selected?.id;
            return (
              <button
                key={result.id}
                type="button"
                onClick={() => setSelectedId(result.id)}
                className={cn(
                  "flex items-center gap-1.5 px-2 py-1.5 rounded-md border text-[10px] font-bold uppercase tracking-wide transition-colors",
                  passed
                    ? "border-green-500/30 text-green-500"
                    : "border-red-500/30 text-red-500",
                  active ? "bg-white/10" : "bg-transparent hover:bg-white/5",
                )}
              >
                {passed ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                Case {index + 1}
                {hidden && <EyeOff className="w-3 h-3 ml-auto opacity-50" />}
              </button>
            );
          })}
        </div>

        {selected && (
          <div className="space-y-3">
            {hidden && (
              <div className="bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[10px] font-bold uppercase tracking-widest px-3 py-2 rounded-md">
                Hidden test case
              </div>
            )}
            <div>
              <span className="text-zinc-600 font-bold uppercase tracking-widest text-[9px]">Input</span>
              <pre className="mt-1 font-mono text-[13px] bg-zinc-900 border border-white/10 rounded-md p-3 whitespace-pre-wrap">
                {selected.input}
              </pre>
            </div>
            <div>
              <span className="text-zinc-600 font-bold uppercase tracking-widest text-[9px]">Expected</span>
              {hidden ? (
                <pre className="mt-1 font-mono text-[13px] bg-zinc-900 border border-white/10 rounded-md p-3 text-zinc-600 italic">
                  hidden
                </pre>
              ) : (
                <pre className="mt-1 font-mono text-[13px] bg-zinc-900 border border-white/10 rounded-md p-3 whitespace-pre-wrap">
                  {expectedById?.[selected.id] ?? <span className="italic text-zinc-600">—</span>}
                </pre>
              )}
            </div>
            <div>
              <span className="text-zinc-600 font-bold uppercase tracking-widest text-[9px]">Your Output</span>
              <pre className="mt-1 font-mono text-[13px] bg-zinc-900 border border-white/10 rounded-md p-3 whitespace-pre-wrap">
                {selected.actual_output || <span className="italic text-zinc-600">No output</span>}
              </pre>
            </div>
            {(selected.status === "ERROR" || selected.status === "TIMEOUT") && (
              <div>
                <span className="text-red-500 font-bold uppercase tracking-widest text-[9px]">
                  Error Logs
                </span>
                <pre className="mt-1 font-mono text-[13px] bg-red-950/20 border border-red-500/30 text-red-400 rounded-md p-3 whitespace-pre-wrap">
                  {selected.status_description || selected.status}
                  {selected.error ? `\n${selected.error}` : ""}
                  {selected.stdout_truncated ? "\n(stdout truncated)" : ""}
                </pre>
              </div>
            )}
          </div>
        )}

        {summary?.feedback ? (
          <p className="text-xs text-zinc-400 border-t border-white/10 pt-4">{summary.feedback}</p>
        ) : (
          summary &&
          onRequestFeedback && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRequestFeedback}
              disabled={feedbackLoading}
              className="w-full text-[10px]"
            >
              {feedbackLoading ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <MessageCircle className="mr-2 h-3.5 w-3.5" />
              )}
              {feedbackLoading ? "Getting feedback..." : "Get Feedback"}
            </Button>
          )
        )}
      </div>
    </ScrollArea>
  );
}
