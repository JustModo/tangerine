import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Flag, Flame, Play, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";
import { cn } from "~/lib/utils";
import type { Progress, RevisionCandidate } from "~/lib/types";

const REASON_LABEL: Record<RevisionCandidate["reason"], string> = {
  weak_skill: "Struggled with this",
  overdue_revision: "Not seen in a while",
  review: "Keep it warm",
};

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border border-white/10 px-5 py-4">
      <p className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">{label}</p>
      <p className="text-2xl font-black tracking-tighter mt-1">{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h2 className="text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500">{title}</h2>
      {children}
    </div>
  );
}

export default function ProgressScreen() {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [startingSkillId, setStartingSkillId] = useState<string | null>(null);
  const navigate = useNavigate();
  const { showError, setBusyMessage } = useStatus();

  async function load() {
    try {
      const user = await apiJson<{ id: string }>("/api/users/me");
      setProgress(await apiJson<Progress>(`/api/users/${user.id}/progress`));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load your progress");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Practice needs a language, and a skill on its own doesn't carry one. Python is the
   * default rather than a prompt: this is a one-click button, and a modal to pick a
   * language would defeat the point. */
  async function practice(skillId: string) {
    setStartingSkillId(skillId);
    setBusyMessage("Finding a problem...");
    try {
      const session = await apiJson<{ id: string }>("/api/problem-sessions/practice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_id: skillId, language: "python" }),
      });
      navigate(`/problem-sessions/${session.id}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Couldn't start a practice problem");
    } finally {
      setStartingSkillId(null);
      setBusyMessage(null);
    }
  }

  if (!progress) return null;

  const due = progress.revision_queue.slice(0, 3);
  const hasRecord = progress.skills.length > 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full">
      <PageHeader title="Progress" subtitle="What you've practised and what's due" backTo="/" />
      <div className="flex-1 min-h-0 overflow-y-auto w-full">
        <div className="max-w-3xl mx-auto flex flex-col gap-10 py-10 px-10">
          {!hasRecord && (
            <p className="text-zinc-500 text-xs uppercase tracking-widest py-8 text-center">
              Nothing here yet. Solve a problem and this fills in.
            </p>
          )}

          {hasRecord && (
            <>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Solved" value={progress.solved_total} />
                <Stat label="This week" value={progress.solved_this_week} />
                <Stat
                  label="Best streak"
                  value={
                    <span className="flex items-center gap-2">
                      {progress.best_streak}
                      {progress.best_streak > 0 && <Flame className="w-5 h-5 text-amber-500" />}
                    </span>
                  }
                />
              </div>

              {due.length > 0 && (
                <Section title="Due today">
                  <div className="flex flex-col divide-y divide-white/5 border-y border-white/10">
                    {due.map((candidate) => (
                      <div
                        key={candidate.skill_id}
                        className="py-4 flex items-center justify-between gap-4"
                      >
                        <div className="min-w-0">
                          <p className="text-sm font-bold uppercase tracking-wide truncate">
                            {candidate.skill_name}
                          </p>
                          <p className="text-zinc-500 text-[10px] uppercase tracking-widest">
                            {REASON_LABEL[candidate.reason]} ·{" "}
                            {Math.round(candidate.days_since_seen)}d ago
                          </p>
                        </div>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={startingSkillId !== null}
                          onClick={() => practice(candidate.skill_id)}
                        >
                          {startingSkillId === candidate.skill_id ? (
                            <RefreshCcw className="w-3.5 h-3.5 mr-2 animate-spin" />
                          ) : (
                            <Play className="w-3.5 h-3.5 mr-2" />
                          )}
                          PRACTISE
                        </Button>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              <Section title="Skills">
                <div className="space-y-2">
                  {progress.skills.map((skill) => (
                    <div key={skill.skill_id} className="space-y-1">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-xs uppercase tracking-wide truncate">
                          {skill.skill_name}
                        </span>
                        <span className="text-[10px] font-mono tabular-nums text-zinc-500 flex-none">
                          {Math.round(skill.mastery_score * 100)}%
                        </span>
                      </div>
                      <div className="h-1 bg-white/5">
                        <div
                          className={cn(
                            "h-full",
                            skill.mastery_score > 0.7
                              ? "bg-green-500"
                              : skill.mastery_score < 0.4
                                ? "bg-red-500/70"
                                : "bg-zinc-400",
                          )}
                          style={{ width: `${Math.max(skill.mastery_score * 100, 2)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            </>
          )}

          {progress.flagged.length > 0 && (
            <Section title="Flagged">
              <div className="flex flex-col divide-y divide-white/5 border-y border-white/10">
                {progress.flagged.map((item) => (
                  <button
                    key={item.problem_session_id}
                    type="button"
                    onClick={() => navigate(`/problem-sessions/${item.problem_session_id}`)}
                    className="py-4 flex items-center justify-between gap-4 text-left hover:bg-zinc-950 transition-colors px-2"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-bold uppercase tracking-wide truncate">
                        {item.title}
                      </p>
                      <p className="text-zinc-500 text-[10px] uppercase tracking-widest">
                        {item.difficulty}
                      </p>
                    </div>
                    <Flag className="w-4 h-4 flex-none text-amber-500 fill-current" />
                  </button>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
