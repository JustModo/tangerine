import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiJson } from "~/lib/api";
import type { LessonNotes } from "~/lib/types";

/**
 * Teaching cheat sheet for one lesson node, revealed a step at a time. Fetching happens on
 * mount — both callers only mount this once the user actually opens notes, so mounting IS
 * the lazy trigger and a node whose notes are never opened costs zero tokens.
 */
export function LessonNotesPanel({ lessonNodeId }: { lessonNodeId: string }) {
  const [notes, setNotes] = useState<LessonNotes | null>(null);
  const [failed, setFailed] = useState(false);
  const [revealed, setRevealed] = useState(1);

  useEffect(() => {
    let cancelled = false;
    setNotes(null);
    setFailed(false);
    setRevealed(1);
    apiJson<LessonNotes>(`/api/learning-plans/nodes/${lessonNodeId}/notes`)
      .then((data) => !cancelled && setNotes(data))
      // Deliberately not showError() — a cheat sheet failing shouldn't throw a global
      // banner over the editor. Inline message is enough.
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [lessonNodeId]);

  if (failed) {
    return (
      <p className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">
        Couldn't load notes.
      </p>
    );
  }

  if (notes === null) {
    return (
      <p className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 animate-pulse">
        Writing notes...
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {notes.steps.slice(0, revealed).map((step, index) => (
        <div key={index} className="space-y-1.5">
          <h4 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">
            {step.title}
          </h4>
          <div className="prose dark:prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{step.body_md}</ReactMarkdown>
          </div>
        </div>
      ))}
      {revealed < notes.steps.length && (
        <button
          type="button"
          onClick={() => setRevealed((n) => n + 1)}
          className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 hover:text-white transition-colors"
        >
          Next step ({revealed + 1} of {notes.steps.length})
        </button>
      )}
    </div>
  );
}
