import { useEffect, useRef, useState } from "react";
import { Flag, Lightbulb, Unlock } from "lucide-react";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { LessonNotesPanel } from "@/components/LessonNotesPanel";
import { CodeHelperPanel } from "./CodeHelperPanel";
import { ApiError, apiJson } from "~/lib/api";
import { useStatus } from "~/lib/status";
import { cn } from "~/lib/utils";
import type { HelperContext, ProblemDetail } from "~/lib/types";
import { SectionLabel } from "@/components/Section";

// Minutes an interview would expect for each difficulty. Shown, never enforced and never
// recorded: notes and the helper chat are free here, so a clock that fed into any score
// would be measuring something it cannot see.
const TARGET_MINUTES: Record<string, number> = { easy: 15, medium: 25, hard: 40 };

type Tab = "statement" | "lesson" | "helper";

function Timer({ difficulty }: { difficulty: string }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const target = TARGET_MINUTES[difficulty.toLowerCase()];
  const minutes = Math.floor(elapsed / 60);
  const over = target !== undefined && minutes >= target;
  return (
    <span
      className={cn(
        "text-[10px] font-mono tabular-nums tracking-widest",
        over ? "text-amber-500" : "text-zinc-600",
      )}
      title={target ? `Interviews usually allow about ${target} min for a ${difficulty}` : undefined}
    >
      {String(minutes).padStart(2, "0")}:{String(elapsed % 60).padStart(2, "0")}
      {target !== undefined && <span className="text-zinc-700"> / {target}:00</span>}
    </span>
  );
}

function SolutionSection({ problemSessionId }: { problemSessionId: string }) {
  const [solution, setSolution] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reveal() {
    try {
      const data = await apiJson<{ reference_solution: string }>(
        `/api/problem-sessions/${problemSessionId}/solution`,
      );
      setSolution(data.reference_solution);
    } catch {
      setError("Couldn't load the solution.");
    }
  }

  return (
    <div className="space-y-2 border-t border-white/10 pt-5">
      <SectionLabel>
        Reference solution
      </SectionLabel>
      {solution === null ? (
        <>
          <p className="text-xs text-zinc-500">
            You solved it. Comparing your approach to a clean one is where most of the
            learning is.
          </p>
          <Button variant="secondary" size="sm" onClick={reveal}>
            <Unlock className="w-3.5 h-3.5 mr-2" /> SHOW SOLUTION
          </Button>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </>
      ) : (
        <pre className="text-xs font-mono bg-zinc-900 border border-white/10 p-3 overflow-x-auto">
          {solution}
        </pre>
      )}
    </div>
  );
}

function HintList({
  hints,
  onRevealed,
}: {
  hints: string[];
  onRevealed?: (count: number) => void;
}) {
  const [revealed, setRevealed] = useState(0);
  if (hints.length === 0) return null;

  return (
    <div className="space-y-3">
      <SectionLabel>
        Hints
      </SectionLabel>
      <div className="space-y-2">
        {hints.slice(0, revealed).map((hint, index) => (
          <div
            key={index}
            className="flex gap-2 border border-white/10 bg-white/5 px-3 py-2 text-xs text-zinc-300"
          >
            <Lightbulb className="w-3.5 h-3.5 flex-none text-zinc-500 mt-0.5" />
            <span>{hint}</span>
          </div>
        ))}
        {revealed < hints.length && (
          <button
            type="button"
            onClick={() =>
              setRevealed((n) => {
                // Reported upward so mastery can tell "solved cold" from "solved after
                // three hints" - the same pass otherwise scores identically either way.
                onRevealed?.(n + 1);
                return n + 1;
              })
            }
            className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 hover:text-white transition-colors"
          >
            Reveal hint {revealed + 1} of {hints.length}
          </button>
        )}
      </div>
    </div>
  );
}

export function ProblemPanel({
  problem,
  lessonNodeId,
  problemSessionId,
  getContext,
  onHintRevealed,
  onHelperUsed,
  solved = false,
  initiallyFlagged = false,
}: {
  problem: ProblemDetail;
  lessonNodeId?: string;
  problemSessionId?: string;
  getContext?: () => HelperContext;
  onHintRevealed?: (count: number) => void;
  onHelperUsed?: () => void;
  solved?: boolean;
  initiallyFlagged?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("statement");
  // Mount the lesson and helper only once opened (so a never-opened tab costs zero tokens),
  // then keep them mounted-but-hidden so toggling never refetches or loses a draft.
  const [lessonMounted, setLessonMounted] = useState(false);
  const [helperMounted, setHelperMounted] = useState(false);
  const [flagged, setFlagged] = useState(initiallyFlagged);
  const { showError } = useStatus();
  const tabs: Tab[] = [
    "statement",
    ...(lessonNodeId ? (["lesson"] as const) : []),
    ...(problemSessionId && getContext ? (["helper"] as const) : []),
  ];

  async function toggleFlag() {
    if (!problemSessionId) return;
    const next = !flagged;
    setFlagged(next);
    try {
      await apiJson(`/api/problem-sessions/${problemSessionId}/flag`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flagged: next }),
      });
    } catch (err) {
      setFlagged(!next);
      showError(err instanceof ApiError ? err.message : "Couldn't update the flag");
    }
  }

  return (
    // Fixed header + a single scrolling region below it. The helper tab fills that region
    // exactly, so only its message list scrolls - the panel itself never does.
    <div className="h-full flex flex-col bg-zinc-950 border-r border-white/10">
      <div className="flex-none px-8 pt-8 pb-4 space-y-4">
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3">
            <h1 className="text-2xl font-black tracking-tighter uppercase">{problem.title}</h1>
            <div className="flex items-center gap-2 flex-none pt-1">
              <Timer difficulty={problem.difficulty} />
              {problemSessionId && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={flagged ? "Unflag this problem" : "Flag to come back to"}
                  aria-pressed={flagged}
                  onClick={toggleFlag}
                  className={flagged ? "text-amber-500" : "text-zinc-600 hover:text-white"}
                >
                  <Flag className={cn("w-4 h-4", flagged && "fill-current")} />
                </Button>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{problem.language}</Badge>
            <Badge variant="secondary">{problem.difficulty}</Badge>
            {problem.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
        </div>

        <Separator className="bg-white/10" />

        {tabs.length > 1 && (
          <div className="flex items-center gap-4">
            {tabs.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setTab(value);
                  if (value === "lesson") setLessonMounted(true);
                  if (value === "helper") setHelperMounted(true);
                }}
                className={cn(
                  "text-[10px] font-bold uppercase tracking-widest transition-colors",
                  tab === value ? "text-white" : "text-zinc-500 hover:text-zinc-300",
                )}
              >
                {value}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0">
        {helperMounted && problemSessionId && getContext && (
          <div className={tab === "helper" ? "h-full px-8 pb-8" : "hidden"}>
            <CodeHelperPanel
              problemSessionId={problemSessionId}
              getContext={getContext}
              onFirstMessage={onHelperUsed}
            />
          </div>
        )}

        <ScrollArea className={tab === "helper" ? "hidden" : "h-full"}>
          <div className="px-8 pb-8">
        <div className={tab === "statement" ? "space-y-6" : "hidden"}>
        <Markdown>{problem.statement_md}</Markdown>

        {problem.constraints && (
          <div className="space-y-2">
            <SectionLabel>
              Constraints
            </SectionLabel>
            <pre className="text-xs font-mono bg-zinc-900 border border-white/10 p-3 whitespace-pre-wrap">
              {problem.constraints}
            </pre>
          </div>
        )}

        {problem.examples.length > 0 && (
          <div className="space-y-3">
            <SectionLabel>
              Examples
            </SectionLabel>
            {problem.examples.map((example) => (
              <div key={example.id} className="border border-white/10 p-3 space-y-2 text-xs">
                <div>
                  <span className="text-zinc-600 font-bold uppercase tracking-widest text-[9px]">Input</span>
                  <pre className="font-mono mt-1 whitespace-pre-wrap">{example.input}</pre>
                </div>
                <div>
                  <span className="text-zinc-600 font-bold uppercase tracking-widest text-[9px]">Output</span>
                  <pre className="font-mono mt-1 whitespace-pre-wrap">{example.output}</pre>
                </div>
                {example.explanation && (
                  <div>
                    <span className="text-zinc-600 font-bold uppercase tracking-widest text-[9px]">
                      Explanation
                    </span>
                    {/* Markdown (not plain text) so LaTeX renders here too; remark-breaks
                        keeps the generated one-idea-per-line formatting intact. */}
                    <Markdown className="mt-1 text-zinc-400">{example.explanation}</Markdown>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <HintList hints={problem.hints} onRevealed={onHintRevealed} />

        {solved && problemSessionId && <SolutionSection problemSessionId={problemSessionId} />}
        </div>

        {lessonMounted && lessonNodeId && (
          <div className={tab === "lesson" ? "" : "hidden"}>
            <LessonNotesPanel lessonNodeId={lessonNodeId} />
          </div>
        )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
