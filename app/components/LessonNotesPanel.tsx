import { useState } from "react";
import { RefreshCcw, Sparkles } from "lucide-react";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { apiJson } from "~/lib/api";
import type { LessonNotes } from "~/lib/types";
import { SectionLabel } from "@/components/Section";

/**
 * Teaching lesson for one lesson node's skill, revealed a step at a time. Generation is an
 * explicit action rather than a mount effect: a lesson costs tokens, and opening a tab is
 * not the same as asking for one. Whatever was generated stays until the panel unmounts,
 * so switching tabs never refetches.
 */
export function LessonNotesPanel({ lessonNodeId }: { lessonNodeId: string }) {
  const [notes, setNotes] = useState<LessonNotes | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [revealed, setRevealed] = useState(1);

  async function generate(refresh = false) {
    setLoading(true);
    setFailed(false);
    try {
      const data = await apiJson<LessonNotes>(
        `/api/learning-plans/nodes/${lessonNodeId}/notes${refresh ? "?refresh=true" : ""}`,
      );
      setNotes(data);
      setRevealed(1);
    } catch {
      // Deliberately not showError() - a lesson failing shouldn't throw a global banner
      // over the editor. Inline message is enough.
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <SectionLabel>
          Lesson
        </SectionLabel>
        <Button
          variant="secondary"
          size="sm"
          disabled={loading}
          onClick={() => generate(notes !== null)}
        >
          {notes === null ? (
            <>
              <Sparkles className="w-3.5 h-3.5 mr-2" /> GENERATE
            </>
          ) : (
            <>
              <RefreshCcw className="w-3.5 h-3.5 mr-2" /> REGENERATE
            </>
          )}
        </Button>
      </div>

      {loading && (
        <p className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 animate-pulse">
          Writing the lesson...
        </p>
      )}

      {failed && !loading && (
        <p className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">
          Couldn't write the lesson. Try again.
        </p>
      )}

      {notes === null && !loading && !failed && (
        <p className="text-xs text-zinc-500">
          A short lesson on the core concept behind this problem
        </p>
      )}

      {notes !== null && !loading && (
        <div className="space-y-5">
          {notes.steps.slice(0, revealed).map((step, index) => (
            <div key={index} className="space-y-1.5">
              <SectionLabel>
                {step.title}
              </SectionLabel>
              <Markdown>{step.body_md}</Markdown>
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
      )}
    </div>
  );
}
