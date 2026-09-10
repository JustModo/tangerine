import { useEffect, useRef, useState } from "react";
import { Loader2, Swords } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionLabel } from "@/components/Section";
import { STAGE_LABELS } from "~/lib/stages";

const DIFFICULTIES = ["random", "easy", "medium", "hard"];

const SELECT_CLASS =
  "w-full bg-zinc-950 border-l border-white/20 h-10 text-sm px-3 disabled:opacity-50";

/**
 * Test mode's whole configuration surface. Built on <dialog> like ConfirmDialog, so focus
 * trapping, Escape and the top-layer backdrop come from the platform.
 *
 * It stays open while generating rather than handing off to the global busy pill: this is
 * a 30-90s wait with no cache behind it, and the stage list is the only evidence the
 * request is alive.
 */
export function TestModeDialog({
  open,
  languages,
  initialLanguage,
  busyStage,
  onStart,
  onClose,
}: {
  open: boolean;
  languages: string[];
  initialLanguage: string;
  busyStage: string | null;
  onStart: (options: { language: string; difficulty: string; topic: string }) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [language, setLanguage] = useState(initialLanguage);
  const [difficulty, setDifficulty] = useState("random");
  const [topic, setTopic] = useState("");
  const running = busyStage !== null;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    setLanguage(initialLanguage);
  }, [initialLanguage]);

  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault();
        // Escape must not orphan a generation that is already running.
        if (!running) onClose();
      }}
      className="m-0 max-w-none max-h-none w-screen h-screen bg-black p-0 backdrop:bg-black"
    >
      <div className="h-full w-full flex flex-col text-white">
        <div className="flex-none px-6 py-3 flex items-center justify-between border-b border-white/10">
          <div className="flex items-center gap-3">
            <Swords className="w-4 h-4" />
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.5em] text-zinc-500">
                Tangerine
              </p>
              <p className="text-sm font-bold uppercase tracking-wide">Test Mode</p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            disabled={running}
            className="text-zinc-500 hover:text-white"
          >
            Close
          </Button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-10 py-12 flex">
          <div className="max-w-lg mx-auto my-auto w-full space-y-10">
            <h2 className="text-3xl font-black tracking-tighter uppercase">Test Mode</h2>

            <div className="space-y-6">
              <div className="space-y-2">
                <SectionLabel as="p">Language</SectionLabel>
                <select
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                  disabled={running}
                  className={SELECT_CLASS}
                >
                  {languages.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <SectionLabel as="p">Difficulty</SectionLabel>
                <select
                  value={difficulty}
                  onChange={(event) => setDifficulty(event.target.value)}
                  disabled={running}
                  className={SELECT_CLASS}
                >
                  {DIFFICULTIES.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <SectionLabel as="p">Topic</SectionLabel>
                <Input
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  disabled={running}
                  maxLength={60}
                  placeholder="graphs, two pointers, dp on trees..."
                />
                <p className="text-[10px] text-zinc-600 uppercase tracking-widest">
                  Leave empty to draw one at random
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <Button
                size="sm"
                className="w-full tracking-[0.3em]"
                disabled={running}
                onClick={() => onStart({ language, difficulty, topic: topic.trim() })}
              >
                {running ? "Generating..." : "Start Test"}
              </Button>
              {running && (
                <div className="flex items-center gap-3 text-zinc-400">
                  <Loader2 className="w-4 h-4 animate-spin flex-none" />
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-widest truncate">
                      {STAGE_LABELS[busyStage] ?? STAGE_LABELS.generating}
                    </p>
                    <p className="text-[10px] text-zinc-600 uppercase tracking-widest">
                      Writing a new question, this takes up to a minute
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </dialog>
  );
}
