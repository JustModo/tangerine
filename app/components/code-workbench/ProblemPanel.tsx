import { useState } from "react";
import { Lightbulb } from "lucide-react";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { LessonNotesPanel } from "@/components/LessonNotesPanel";
import { CodeHelperPanel } from "./CodeHelperPanel";
import { cn } from "~/lib/utils";
import type { HelperContext, ProblemDetail } from "~/lib/types";

function HintList({ hints }: { hints: string[] }) {
  const [revealed, setRevealed] = useState(0);
  if (hints.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
        Hints
      </h3>
      <div className="space-y-2">
        {hints.slice(0, revealed).map((hint, index) => (
          <div
            key={index}
            className="flex gap-2 border border-white/10 bg-white/5 rounded-md px-3 py-2 text-xs text-zinc-300"
          >
            <Lightbulb className="w-3.5 h-3.5 flex-none text-zinc-500 mt-0.5" />
            <span>{hint}</span>
          </div>
        ))}
        {revealed < hints.length && (
          <button
            type="button"
            onClick={() => setRevealed((n) => n + 1)}
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
}: {
  problem: ProblemDetail;
  lessonNodeId?: string;
  problemSessionId?: string;
  getContext?: () => HelperContext;
}) {
  const [tab, setTab] = useState<"statement" | "notes" | "helper">("statement");
  // Mount the notes/helper panels only once first opened (so never-opened tabs cost zero
  // tokens), then keep them mounted-but-hidden so toggling never refetches or loses a draft.
  const [notesMounted, setNotesMounted] = useState(false);
  const [helperMounted, setHelperMounted] = useState(false);
  const tabs: ("statement" | "notes" | "helper")[] = [
    "statement",
    ...(lessonNodeId ? (["notes"] as const) : []),
    ...(problemSessionId && getContext ? (["helper"] as const) : []),
  ];

  return (
    // Fixed header + a single scrolling region below it. The helper tab fills that region
    // exactly, so only its message list scrolls — the panel itself never does.
    <div className="h-full flex flex-col bg-zinc-950 border-r border-white/10">
      <div className="flex-none px-8 pt-8 pb-4 space-y-4">
        <div className="space-y-3">
          <h1 className="text-2xl font-black tracking-tighter uppercase">{problem.title}</h1>
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
                  if (value === "notes") setNotesMounted(true);
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
            <CodeHelperPanel problemSessionId={problemSessionId} getContext={getContext} />
          </div>
        )}

        <ScrollArea className={tab === "helper" ? "hidden" : "h-full"}>
          <div className="px-8 pb-8">
        {notesMounted && lessonNodeId && (
          <div className={tab === "notes" ? "" : "hidden"}>
            <LessonNotesPanel lessonNodeId={lessonNodeId} />
          </div>
        )}

        <div className={tab === "statement" ? "space-y-6" : "hidden"}>
        <Markdown>{problem.statement_md}</Markdown>

        {problem.constraints && (
          <div className="space-y-2">
            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
              Constraints
            </h3>
            <pre className="text-xs font-mono bg-zinc-900 border border-white/10 rounded-md p-3 whitespace-pre-wrap">
              {problem.constraints}
            </pre>
          </div>
        )}

        {problem.examples.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
              Examples
            </h3>
            {problem.examples.map((example) => (
              <div key={example.id} className="border border-white/10 rounded-md p-3 space-y-2 text-xs">
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

        <HintList hints={problem.hints} />
        </div>
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
