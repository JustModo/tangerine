import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

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

  async function load() {
    const res = await fetch(`/api/learning-plans/${id}`);
    if (!res.ok) {
      toast.error("Plan not found");
      return;
    }
    setPlan(await res.json());
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function acceptPlan() {
    setBusy(true);
    try {
      await fetch(`/api/learning-plans/${id}/accept`, { method: "POST" });
      await load();
    } catch {
      toast.error("Failed to accept plan");
    } finally {
      setBusy(false);
    }
  }

  async function startNext() {
    setBusy(true);
    try {
      const res = await fetch(`/api/learning-plans/${id}/problems/next`, { method: "POST" });
      if (!res.ok) {
        toast.error("Failed to select a problem");
        return;
      }
      const problemSession = await res.json();
      navigate(`/problem-sessions/${problemSession.id}`);
    } catch {
      toast.error("Failed to select a problem");
    } finally {
      setBusy(false);
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
    <div className="flex-1 overflow-y-auto w-full">
      <div className="max-w-2xl mx-auto flex flex-col gap-10 py-16 px-10">
        <div className="space-y-2">
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
          <Button className="h-14 text-xs tracking-[0.3em]" onClick={acceptPlan} disabled={busy}>
            PROCEED
          </Button>
        )}
        {plan.status === "ACCEPTED" && (
          <Button className="h-14 text-xs tracking-[0.3em]" onClick={startNext} disabled={busy}>
            START NEXT PROBLEM
          </Button>
        )}
      </div>
    </div>
  );
}
