import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowLeft, ListTree, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";

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

interface LessonPlanSummary {
  id: string;
  status: string;
  version: number;
}

export default function SessionChat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [plans, setPlans] = useState<LessonPlanSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { showError, setBusyMessage } = useStatus();

  async function loadSession() {
    try {
      setSession(await apiJson<SessionDetail>(`/api/sessions/${id}`));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load session");
    }
  }

  async function loadPlans() {
    try {
      setPlans(await apiJson<LessonPlanSummary[]>(`/api/learning-plans?session_id=${id}`));
    } catch {
      // Non-critical — the "View Plan" button just stays hidden if this fails.
    }
  }

  useEffect(() => {
    loadSession();
    loadPlans();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length]);

  async function sendMessage() {
    if (!draft.trim()) return;
    setSending(true);
    setBusyMessage("Sending message...");
    try {
      // Only clear the draft / reload once the send is actually confirmed — previously
      // this fired-and-forgot, so a dropped connection (e.g. the agent restarting under
      // --reload in dev) silently lost the message while still clearing the input.
      await apiJson(`/api/sessions/${id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: draft }),
      });
      setDraft("");
      await loadSession();
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to send message");
    } finally {
      setSending(false);
      setBusyMessage(null);
    }
  }

  async function generatePlan(topic: string) {
    setGeneratingPlan(true);
    // A single synchronous request under the hood — these are staged, not real backend
    // progress events, just enough feedback that the wait doesn't look frozen.
    setBusyMessage("Generating curriculum...");
    const validatingTimer = setTimeout(() => setBusyMessage("Validating curriculum..."), 2500);
    try {
      const plan = await apiJson<{ id: string }>("/api/learning-plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id, topic, language: "python", level: "beginner" }),
      });
      navigate(`/plans/${plan.id}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to generate a plan");
    } finally {
      clearTimeout(validatingTimer);
      setGeneratingPlan(false);
      setBusyMessage(null);
    }
  }

  async function deleteSession() {
    if (!confirm("Delete this session? This can't be undone.")) return;
    setBusyMessage("Deleting session...");
    try {
      await apiJson(`/api/sessions/${id}`, { method: "DELETE" });
      navigate("/");
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to delete session");
    } finally {
      setBusyMessage(null);
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

  const activePlan =
    plans.find((p) => p.status === "ACCEPTED") ?? [...plans].sort((a, b) => b.version - a.version)[0];

  return (
    <div className="flex-1 flex flex-col min-h-0 max-w-3xl mx-auto w-full">
      <div className="flex-none px-10 py-4 flex items-center justify-between border-b border-white/10 gap-2">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={() => navigate(-1)} aria-label="Back">
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <p className="text-[10px] uppercase tracking-widest text-zinc-500">{session.status}</p>
        </div>
        <div className="flex items-center gap-2">
          {activePlan && (
            <Button
              variant="ghost"
              size="sm"
              className="text-zinc-400 hover:text-white"
              onClick={() => navigate(`/plans/${activePlan.id}`)}
            >
              <ListTree className="w-4 h-4 mr-2" /> VIEW PLAN
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="text-zinc-500 hover:text-red-500 hover:bg-red-950/30"
            onClick={deleteSession}
          >
            <Trash2 className="w-4 h-4 mr-2" /> DELETE
          </Button>
        </div>
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
              <div className="border border-white/10 rounded-md px-4 py-3 text-sm prose prose-invert prose-sm max-w-none prose-p:my-0">
                {message.role === "assistant" ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                ) : (
                  message.content
                )}
              </div>
            </div>
          ))}
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
          placeholder="Message..."
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
