import { useEffect, useState } from "react";
import type { MetaFunction } from "react-router";
import { useNavigate, useParams } from "react-router";
import { CheckCircle2, Lock, MessageSquare, Play, RefreshCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { useStatus } from "~/lib/status";
import { ApiError, apiFetch, apiJson, consumeSSE } from "~/lib/api";
import { cn } from "~/lib/utils";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/Section";

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

/**
 * Real backend stages, not a timer - a bank hit is instant, while a miss can walk through
 * generation, sandbox validation, a repair attempt and a revalidation. The agent reports
 * which one it is actually in (agent/app/curriculum/api/router.py).
 */
const STAGE_LABELS: Record<string, string> = {
  selecting: "Selecting problem...",
  generating: "Generating problem...",
  validating: "Validating problem...",
  patching: "Patching problem...",
  revalidating: "Revalidating...",
  regenerating: "Regenerating problem...",
};

export const meta: MetaFunction = () => [
  { title: "Learning Plan · Tangerine" },
  { name: "description", content: "Your DSA course, step by step. Read the notes, then solve the problem for each step." },
];

export default function PlanScreen() {
  const { id } = useParams();
  const [plan, setPlan] = useState<LessonPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [revisitingNodeId, setRevisitingNodeId] = useState<string | null>(null);
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

  // nodeId is the step whose Play was pressed. Without it the server serves the first
  // unfinished step instead, so pressing Play on one row could open a different one.
  async function startNext(nodeId?: string) {
    setBusy(true);
    setBusyMessage(STAGE_LABELS.selecting);
    try {
      const url = `/api/learning-plans/${id}/problems/next${nodeId ? `?node_id=${nodeId}` : ""}`;
      const response = await apiFetch(url, { method: "POST" });
      let sessionId: string | null = null;
      await consumeSSE(response, (event) => {
        if (event.type === "stage" && typeof event.stage === "string") {
          setBusyMessage(STAGE_LABELS[event.stage] ?? STAGE_LABELS.selecting);
        } else if (event.type === "session" && typeof event.id === "string") {
          sessionId = event.id;
        }
      });
      if (!sessionId) throw new ApiError("The server didn't return a problem.");
      navigate(`/problem-sessions/${sessionId}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to select a problem");
    } finally {
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
                      onClick={() => startNext(node.id)}
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
                </div>
              );
            })}
            {plan.nodes.length === 0 && (
              <EmptyState>No nodes yet.</EmptyState>
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
