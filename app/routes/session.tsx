import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ListTree, Loader2, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/PageHeader";
import { useStatus } from "~/lib/status";
import { ApiError, apiFetch, apiJson } from "~/lib/api";

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
  const [streamingText, setStreamingText] = useState("");
  const [toolLabel, setToolLabel] = useState<string | null>(null);
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
  }, [session?.messages.length, streamingText, toolLabel]);

  async function sendMessage() {
    if (!draft.trim()) return;
    const content = draft;
    setDraft("");
    setSending(true);
    setStreamingText("");
    setToolLabel(null);
    try {
      const response = await apiFetch(`/api/sessions/${id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        showError(`Send failed (${response.status})`);
        return;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          for (const line of chunk.split("\n\n")) {
            if (!line.startsWith("data: ")) continue;
            const dataStr = line.replace("data: ", "");
            if (dataStr === "{}" || !dataStr.trim()) continue;
            let event: { type: string; delta?: string; label?: string };
            try {
              event = JSON.parse(dataStr);
            } catch {
              continue;
            }
            if (event.type === "user_message") {
              await loadSession();
            } else if (event.type === "text_delta") {
              setStreamingText((prev) => prev + (event.delta || ""));
            } else if (event.type === "tool_start") {
              setToolLabel(event.label || "Working...");
            } else if (event.type === "done") {
              await loadSession();
              await loadPlans();
            }
          }
        }
      }
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to send message");
    } finally {
      setSending(false);
      setStreamingText("");
      setToolLabel(null);
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

  const activePlan =
    plans.find((p) => p.status === "ACCEPTED") ?? [...plans].sort((a, b) => b.version - a.version)[0];

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full">
      <PageHeader
        subtitle={session.status}
        backTo="/"
        actions={
          <>
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
          </>
        }
      />
      <div className="flex-1 flex flex-col min-h-0 max-w-3xl mx-auto w-full">
        <ScrollArea className="flex-1 min-h-0 px-10 py-10">
          <div className="flex flex-col gap-6">
            {session.messages.length === 0 && !streamingText && (
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
                {message.role === "system" ? (
                  <p className="text-xs italic text-zinc-500 px-1">{message.content}</p>
                ) : (
                  <div className="border border-white/10 rounded-md px-4 py-3 text-sm prose prose-invert prose-sm max-w-none prose-p:my-0">
                    {message.role === "assistant" ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    ) : (
                      message.content
                    )}
                  </div>
                )}
              </div>
            ))}
            {toolLabel && (
              <div className="self-start flex items-center gap-2 text-xs italic text-zinc-500 px-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                {toolLabel}
              </div>
            )}
            {streamingText && (
              <div className="self-start max-w-lg">
                <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">assistant</p>
                <div className="border border-white/10 rounded-md px-4 py-3 text-sm prose prose-invert prose-sm max-w-none prose-p:my-0">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingText}</ReactMarkdown>
                </div>
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
    </div>
  );
}
