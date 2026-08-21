import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  intent: string | null;
  created_at: string;
}

interface SessionDetail {
  id: string;
  status: string;
  messages: ChatMessage[];
}

export default function SessionChat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);

  async function loadSession() {
    const res = await fetch(`/api/learning/sessions/${id}`);
    if (!res.ok) {
      toast.error("Session not found");
      return;
    }
    setSession(await res.json());
  }

  useEffect(() => {
    loadSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function sendMessage() {
    if (!draft.trim()) return;
    setSending(true);
    try {
      await fetch(`/api/learning/sessions/${id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: draft }),
      });
      setDraft("");
      await loadSession();
    } catch {
      toast.error("Failed to send message");
    } finally {
      setSending(false);
    }
  }

  async function generatePlan(topic: string) {
    setGeneratingPlan(true);
    try {
      const res = await fetch("/api/learning/plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id, topic, language: "python", level: "beginner" }),
      });
      if (!res.ok) {
        toast.error("Failed to generate a plan");
        return;
      }
      const plan = await res.json();
      navigate(`/plans/${plan.id}`);
    } catch {
      toast.error("Failed to generate a plan");
    } finally {
      setGeneratingPlan(false);
    }
  }

  if (!session) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500 text-xs uppercase tracking-widest">
        Loading session...
      </div>
    );
  }

  const lastLearningPlanMessage = [...session.messages]
    .reverse()
    .find((message) => message.intent === "learning_plan");

  return (
    <div className="flex-1 flex flex-col min-h-0 max-w-3xl mx-auto w-full">
      <ScrollArea className="flex-1 px-10 py-10">
        <div className="flex flex-col gap-6">
          {session.messages.length === 0 && (
            <p className="text-zinc-500 text-xs uppercase tracking-widest text-center py-10">
              What do you want to learn?
            </p>
          )}
          {session.messages.map((message) => (
            <div
              key={message.id}
              className={message.role === "user" ? "self-end max-w-lg" : "self-start max-w-lg"}
            >
              <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">
                {message.role}
              </p>
              <div className="border border-white/10 rounded-md px-4 py-3 text-sm">
                {message.content}
              </div>
            </div>
          ))}
          {/* Assistant replies (clarification) land here once the intent graph asks
              a targeted question — for now, a classified learning_plan intent surfaces
              this action instead. */}
          {lastLearningPlanMessage && (
            <div className="self-center">
              <Button
                className="h-12 px-8 text-xs tracking-[0.3em]"
                onClick={() => generatePlan(lastLearningPlanMessage.content)}
                disabled={generatingPlan}
              >
                GENERATE LEARNING PLAN
              </Button>
            </div>
          )}
        </div>
      </ScrollArea>
      <div className="px-10 py-6 border-t border-white/10 flex gap-4">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="I want to learn prefix sums..."
          className="flex-1 resize-none h-14"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
        />
        <Button className="h-14 px-8 text-xs tracking-[0.3em]" onClick={sendMessage} disabled={sending}>
          SEND
        </Button>
      </div>
    </div>
  );
}
