import { useEffect, useState } from "react";
import type { MetaFunction } from "react-router";
import { useNavigate } from "react-router";
import { Flag, Flame, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/PageHeader";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";
import { cn } from "~/lib/utils";
import type { Progress, ProblemSummary, ProblemsPage } from "~/lib/types";

const SKILLS_PAGE_SIZE = 10;
// Mirrors the backend's Language enum (agent/app/shared/types.py) — no endpoint exposes
// the language list to the frontend today, so this is the one place it's hardcoded.
const LANGUAGES = ["python", "cpp", "c", "java"];

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

/** Local prev/next pager, shared by the Skills list (paged client-side, already in hand)
 * and the All problems list (paged server-side). */
function Pager({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between pt-1">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="text-zinc-500 hover:text-white disabled:opacity-30 disabled:hover:text-zinc-500"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <p className="text-[10px] uppercase tracking-widest text-zinc-500">
        Page {page} of {totalPages}
      </p>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
        className="text-zinc-500 hover:text-white disabled:opacity-30 disabled:hover:text-zinc-500"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  );
}

export const meta: MetaFunction = () => [
  { title: "Progress · Tangerine" },
  { name: "description", content: "What you have practised, what you are weak in, and which skills are due for revision." },
];

export default function ProgressScreen() {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [skillsPage, setSkillsPage] = useState(1);
  const navigate = useNavigate();
  const { showError, setBusyMessage } = useStatus();

  const [query, setQuery] = useState("");
  const [languageFilter, setLanguageFilter] = useState("");
  const [problemsPage, setProblemsPage] = useState(1);
  const [problems, setProblems] = useState<ProblemsPage | null>(null);
  const [openingProblemId, setOpeningProblemId] = useState<string | null>(null);

  async function load() {
    try {
      const user = await apiJson<{ id: string }>("/api/users/me");
      setProgress(await apiJson<Progress>(`/api/users/${user.id}/progress`));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load your progress");
    }
  }

  async function loadProblems(page: number, q: string, language: string) {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "10" });
      if (q.trim()) params.set("q", q.trim());
      if (language) params.set("language", language);
      setProblems(await apiJson<ProblemsPage>(`/api/problems/all?${params}`));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load problems");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced search: a fresh query always restarts pagination at page 1.
  useEffect(() => {
    const handle = setTimeout(() => {
      setProblemsPage(1);
      loadProblems(1, query, languageFilter);
    }, 300);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  // A language change re-filters immediately (no debounce needed for a select) and also
  // restarts pagination at page 1.
  useEffect(() => {
    setProblemsPage(1);
    loadProblems(1, query, languageFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [languageFilter]);

  useEffect(() => {
    loadProblems(problemsPage, query, languageFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemsPage]);

  async function toggleFlag(problem: ProblemSummary) {
    const next = !problem.flagged;
    setProblems((prev) =>
      prev
        ? { ...prev, items: prev.items.map((p) => (p.id === problem.id ? { ...p, flagged: next } : p)) }
        : prev,
    );
    try {
      await apiJson("/api/problem-sessions/flag-for-problem", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ problem_id: problem.id, flagged: next }),
      });
    } catch (err) {
      setProblems((prev) =>
        prev
          ? { ...prev, items: prev.items.map((p) => (p.id === problem.id ? { ...p, flagged: !next } : p)) }
          : prev,
      );
      showError(err instanceof ApiError ? err.message : "Couldn't update the flag");
    }
  }

  async function openProblem(problem: ProblemSummary) {
    setOpeningProblemId(problem.id);
    setBusyMessage("Opening problem...");
    try {
      const session = await apiJson<{ id: string }>("/api/problem-sessions/start-for-problem", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ problem_id: problem.id }),
      });
      navigate(`/problem-sessions/${session.id}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Couldn't open that problem");
    } finally {
      setOpeningProblemId(null);
      setBusyMessage(null);
    }
  }

  if (!progress) return null;

  const hasRecord = progress.skills.length > 0;
  const skillsTotalPages = Math.max(1, Math.ceil(progress.skills.length / SKILLS_PAGE_SIZE));
  const visibleSkills = progress.skills.slice(
    (skillsPage - 1) * SKILLS_PAGE_SIZE,
    skillsPage * SKILLS_PAGE_SIZE,
  );
  const problemsTotalPages = Math.max(1, Math.ceil((problems?.total ?? 0) / (problems?.page_size ?? 10)));

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full">
      <PageHeader title="Progress" subtitle="What you've practised and what's due" />
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

              <Section title="Skills">
                <div className="space-y-2">
                  {visibleSkills.map((skill) => (
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
                <Pager page={skillsPage} totalPages={skillsTotalPages} onChange={setSkillsPage} />
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

          <Section title="All problems">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search title, description, tags, language..."
                  className="pl-9 h-9 text-xs"
                />
              </div>
              <select
                value={languageFilter}
                onChange={(event) => setLanguageFilter(event.target.value)}
                className="bg-zinc-950 border-l border-white/20 h-9 text-xs px-3 flex-none"
              >
                <option value="">All languages</option>
                {LANGUAGES.map((language) => (
                  <option key={language} value={language}>
                    {language}
                  </option>
                ))}
              </select>
            </div>

            {problems && problems.items.length === 0 && (
              <p className="text-zinc-500 text-xs uppercase tracking-widest py-6 text-center">
                {query.trim() ? "No matches." : "Nothing generated yet."}
              </p>
            )}

            {problems && problems.items.length > 0 && (
              <div className="flex flex-col divide-y divide-white/5 border-y border-white/10">
                {problems.items.map((problem) => (
                  <div key={problem.id} className="flex items-center gap-2 px-2">
                    <button
                      type="button"
                      disabled={openingProblemId !== null}
                      onClick={() => openProblem(problem)}
                      className="flex-1 min-w-0 py-4 flex items-center justify-between gap-4 text-left hover:bg-zinc-950 transition-colors disabled:opacity-50"
                    >
                      <div className="min-w-0">
                        <p className="text-sm font-bold uppercase tracking-wide truncate">
                          {problem.title}
                        </p>
                        <p className="text-zinc-500 text-[10px] uppercase tracking-widest truncate">
                          {problem.language} · {problem.difficulty}
                          {problem.tags.length > 0 && ` · ${problem.tags.join(", ")}`}
                        </p>
                      </div>
                    </button>
                    <button
                      type="button"
                      aria-label={problem.flagged ? "Unflag this problem" : "Flag to come back to"}
                      aria-pressed={problem.flagged}
                      onClick={() => toggleFlag(problem)}
                      className={cn(
                        "flex-none p-1",
                        problem.flagged ? "text-amber-500" : "text-zinc-600 hover:text-white",
                      )}
                    >
                      <Flag className={cn("w-4 h-4", problem.flagged && "fill-current")} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <Pager page={problemsPage} totalPages={problemsTotalPages} onChange={setProblemsPage} />
          </Section>
        </div>
      </div>
    </div>
  );
}
