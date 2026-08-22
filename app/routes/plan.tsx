import { useEffect, useState } from "react";
import type { MetaFunction } from "react-router";
import { useNavigate, useParams } from "react-router";
import { BookOpen, CheckCircle2, Lock, MessageSquare, Play, RefreshCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { LessonNotesPanel } from "@/components/LessonNotesPanel";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";
import { cn } from "~/lib/utils";
import { ConfirmDialog } from "@/components/ConfirmDialog";

interface LessonNode {
  id: string;
  skill_name: string | null;
  sequence_index: number;
  status: string;
  difficulty: string | null;
}

interface LessonPlan {
  id: string;
  session_id: string;
  topic: string;
  language: string;
  level: string;
  nodes: LessonNode[];
}

export const meta: MetaFunction = () => [
  { title: "Learning Plan · Tangerine" },
  { name: "description", content: "Your DSA course, step by step. Read the notes, then solve the problem for each step." },
];

export default function PlanScreen() {
  const { id } = useParams();
  const [plan, setPlan] = useState<LessonPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [revisitingNodeId, setRevisitingNodeId] = useState<string | null>(null);
  const [notesNodeId, setNotesNodeId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const navigate = useNavigate();
  const { showError, setBusyMessage } = useStatus();

  async function load() {
    try {
      setPlan(await apiJson<LessonPlan>(`/api/learning-plans/${id}`));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load plan");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function startNext() {
    setBusy(true);
    // Staged, not real backend progress - the bank-hit path is instant, but a miss
    // triggers generation + sandbox validation, which can take a few seconds.
    setBusyMessage("Selecting problem...");
    const generatingTimer = setTimeout(() => setBusyMessage("Generating problem..."), 1200);
    const validatingTimer = setTimeout(() => setBusyMessage("Validating problem..."), 3500);
    try {
      const problemSession = await apiJson<{ id: string }>(
        `/api/learning-plans/${id}/problems/next`,
        { method: "POST" },
      );
      navigate(`/problem-sessions/${problemSession.id}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to select a problem");
    } finally {
      clearTimeout(generatingTimer);
      clearTimeout(validatingTimer);
      setBusy(false);
      setBusyMessage(null);
    }
  }

  async function revisitNode(nodeId: string) {
    setRevisitingNodeId(nodeId);
    try {
      const problemSession = await apiJson<{ id: string }>(`/api/problem-sessions/by-node/${nodeId}`);
      navigate(`/problem-sessions/${problemSession.id}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to reopen this problem");
    } finally {
      setRevisitingNodeId(null);
    }
  }

  async function deleteSession() {
    if (!plan) return;
    setBusyMessage("Deleting session...");
    try {
      await apiJson(`/api/sessions/${plan.session_id}`, { method: "DELETE" });
      navigate("/");
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to delete session");
    } finally {
      setBusyMessage(null);
    }
  }

  if (!plan) return null;

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full">
      <PageHeader
        title={plan.topic}
        subtitle={`${plan.language} · ${plan.level}`}
        backTo="/"
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              className="text-zinc-400 hover:text-white"
              onClick={() => navigate(`/sessions/${plan.session_id}`)}
            >
              <MessageSquare className="w-4 h-4 mr-2" /> CHAT
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-zinc-500 hover:text-red-500 hover:bg-red-950/30"
              onClick={() => setConfirmOpen(true)}
            >
              <Trash2 className="w-4 h-4 mr-2" /> DELETE
            </Button>
          </>
        }
      />
      <div className="flex-1 min-h-0 overflow-y-auto w-full">
        <div className="max-w-3xl mx-auto flex flex-col gap-8 py-10 px-10">
          <div className="relative flex flex-col border-t border-white/5">
            {plan.nodes.length > 1 && (
              <div className="absolute left-5 top-8 bottom-8 w-px bg-white/10" />
            )}
            {plan.nodes.map((node) => {
              const isDone = node.status === "DONE";
              const isLocked = node.status === "LOCKED";
              const isActionable = node.status === "AVAILABLE" || node.status === "IN_PROGRESS";
              return (
                <div key={node.id} className="relative">
                  <div className={cn("relative flex items-center gap-4 py-3", isDone && "opacity-40")}>
                  {isActionable ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={startNext}
                      disabled={busy}
                      aria-label="Start"
                      className="relative z-10 border border-white/10 bg-black flex-none"
                    >
                      {busy ? (
                        <RefreshCcw className="w-4 h-4 animate-spin" />
                      ) : (
                        <Play className="w-4 h-4" />
                      )}
                    </Button>
                  ) : isDone ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => revisitNode(node.id)}
                      disabled={revisitingNodeId === node.id}
                      aria-label="Revisit"
                      className="relative z-10 border border-white/10 bg-black flex-none"
                    >
                      {revisitingNodeId === node.id ? (
                        <RefreshCcw className="w-4 h-4 animate-spin text-zinc-600" />
                      ) : (
                        <CheckCircle2 className="w-4 h-4 text-zinc-600" />
                      )}
                    </Button>
                  ) : (
                    <span className="relative z-10 w-10 h-10 border border-white/10 bg-black flex items-center justify-center flex-none">
                      <Lock className="w-4 h-4 text-zinc-500" />
                    </span>
                  )}
                  <div className="flex-1 min-w-0 flex items-center justify-between gap-2">
                    <span className="text-sm font-bold uppercase tracking-wide truncate">
                      {node.sequence_index + 1}. {node.skill_name || node.id}
                    </span>
                    <div className="flex items-center gap-2 flex-none">
                      {node.difficulty && (
                        <span className="text-[10px] font-black uppercase tracking-widest text-zinc-500 border border-white/10 px-2 py-1">
                          {node.difficulty}
                        </span>
                      )}
                      {/* Hidden on locked rows: reading ahead contradicts the lock and would
                          generate notes for a node the learner may never reach. */}
                      {!isLocked && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Lesson notes"
                          className="text-zinc-500 hover:text-white"
                          onClick={() =>
                            setNotesNodeId((current) => (current === node.id ? null : node.id))
                          }
                        >
                          <BookOpen className="w-4 h-4" />
                        </Button>
                      )}
                      <span
                        className={cn(
                          "text-[10px] font-black uppercase tracking-widest",
                          isDone && "text-zinc-600",
                          isLocked && "text-zinc-500",
                          node.status === "IN_PROGRESS" && "text-white",
                          node.status === "AVAILABLE" && "text-zinc-300",
                        )}
                      >
                        {node.status.replace("_", " ")}
                      </span>
                    </div>
                  </div>
                  </div>
                  {notesNodeId === node.id && (
                    <div className="pl-14 pb-6">
                      <LessonNotesPanel lessonNodeId={node.id} />
                    </div>
                  )}
                </div>
              );
            })}
            {plan.nodes.length === 0 && (
              <p className="text-zinc-500 text-xs uppercase py-8 text-center">No nodes yet.</p>
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title="Delete this session?"
        body="Its plan, problems and chat history go with it. This can't be undone."
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          deleteSession();
        }}
      />

    </div>
  );
}
