import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";

interface LessonNode {
  id: string;
  skill_name: string | null;
  sequence_index: number;
  status: string;
}

interface LessonPlan {
  id: string;
  topic: string;
  language: string;
  level: string;
  status: string;
  nodes: LessonNode[];
}

export default function PlanScreen() {
  const { id } = useParams();
  const [plan, setPlan] = useState<LessonPlan | null>(null);
  const [busy, setBusy] = useState(false);
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

  async function acceptPlan() {
    setBusy(true);
    setBusyMessage("Accepting plan...");
    try {
      await apiJson(`/api/learning-plans/${id}/accept`, { method: "POST" });
      await load();
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to accept plan");
    } finally {
      setBusy(false);
      setBusyMessage(null);
    }
  }

  async function startNext() {
    setBusy(true);
    // Staged, not real backend progress — the bank-hit path is instant, but a miss
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

  if (!plan) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500 text-xs uppercase tracking-widest">
        Loading plan...
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto w-full">
      <div className="max-w-2xl mx-auto flex flex-col gap-10 py-16 px-10">
        <div className="space-y-2">
          <Button
            variant="ghost"
            size="icon"
            className="-ml-2 mb-2"
            onClick={() => navigate(-1)}
            aria-label="Back"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <p className="text-zinc-500 text-[10px] font-bold uppercase tracking-[0.4em]">
            {plan.language} · {plan.level} · {plan.status}
          </p>
          <h1 className="text-4xl font-black tracking-tighter uppercase">{plan.topic}</h1>
        </div>

        <div className="flex flex-col divide-y divide-white/5 border-t border-b border-white/5">
          {plan.nodes.map((node) => (
            <div key={node.id} className="py-5 flex items-center justify-between">
              <span className="text-sm font-bold uppercase tracking-wide">
                {node.sequence_index + 1}. {node.skill_name || node.id}
              </span>
              <span className="text-[10px] font-black uppercase tracking-widest text-zinc-500">
                {node.status}
              </span>
            </div>
          ))}
          {plan.nodes.length === 0 && (
            <p className="text-zinc-500 text-xs uppercase py-8 text-center">No nodes yet.</p>
          )}
        </div>

        {plan.status === "DRAFT" && (
          <Button className="tracking-[0.3em]" onClick={acceptPlan} disabled={busy}>
            PROCEED
          </Button>
        )}
        {plan.status === "ACCEPTED" && (
          <Button className="tracking-[0.3em]" onClick={startNext} disabled={busy}>
            START NEXT PROBLEM
          </Button>
        )}
      </div>
    </div>
  );
}
