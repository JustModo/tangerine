import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
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
  const bottomRef = useRef<HTMLDivElement>(null);

  async function loadSession() {
    const res = await fetch(`/api/sessions/${id}`);
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length]);

  async function sendMessage() {
    if (!draft.trim()) return;
    setSending(true);
    try {
      await fetch(`/api/sessions/${id}/messages`, {
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
      const res = await fetch("/api/learning-plans", {
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

  async function deleteSession() {
    if (!confirm("Delete this session? This can't be undone.")) return;
    try {
      const res = await fetch(`/api/sessions/${id}`, { method: "DELETE" });
      if (!res.ok) {
        toast.error("Failed to delete session");
        return;
      }
      navigate("/");
    } catch {
      toast.error("Failed to delete session");
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
      <div className="flex-none px-10 py-4 flex items-center justify-between border-b border-white/10">
        <p className="text-[10px] uppercase tracking-widest text-zinc-500">{session.status}</p>
        <Button
          variant="ghost"
          size="sm"
          className="text-zinc-500 hover:text-red-500 hover:bg-red-950/30"
          onClick={deleteSession}
        >
          <Trash2 className="w-4 h-4 mr-2" /> DELETE
        </Button>
      </div>
      <ScrollArea className="flex-1 min-h-0 px-10 py-10">
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
                className="tracking-[0.3em]"
                onClick={() => generatePlan(lastLearningPlanMessage.content)}
                disabled={generatingPlan}
              >
                GENERATE LEARNING PLAN
              </Button>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
      <div className="flex-none px-10 py-6 border-t border-white/10 flex items-center gap-4">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="I want to learn prefix sums..."
          className="flex-1 resize-none min-h-0 h-10 py-2"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
        />
        <Button onClick={sendMessage} disabled={sending} className="tracking-[0.3em]">
          SEND
        </Button>
      </div>
    </div>
  );
}
