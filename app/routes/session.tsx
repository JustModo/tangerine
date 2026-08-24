import { useEffect, useRef, useState } from "react";
import type { MetaFunction } from "react-router";
import { useNavigate, useParams } from "react-router";
import { ListTree, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/Markdown";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/PageHeader";
import { useStatus } from "~/lib/status";
import { ApiError, apiFetch, apiJson, consumeSSE } from "~/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/Section";
import { ChatActivity, THINKING } from "@/components/ChatActivity";

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
}

export const meta: MetaFunction = () => [
  { title: "Plan Chat · Tangerine" },
  { name: "description", content: "Tell Tangerine what you want to get better at, and it builds or edits your DSA learning plan." },
];

export default function SessionChat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [plans, setPlans] = useState<LessonPlanSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [activity, setActivity] = useState<string | null>(null);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
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
      // Non-critical - the "View Plan" button just stays hidden if this fails.
    }
  }

  useEffect(() => {
    loadSession();
    loadPlans();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length, streamingText, activity, pendingMessage]);

  // Autosize the composer: 1 line at rest, growing to at most 3 before it scrolls.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 24;
    const padding = el.offsetHeight - el.clientHeight + 16; // borders + py-2 top/bottom
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, lineHeight * 3 + padding)}px`;
  }, [draft]);

  async function sendMessage() {
    if (!draft.trim()) return;
    const content = draft;
    setDraft("");
    setSending(true);
    setStreamingText("");
    // Shown immediately; loadSession() would otherwise round-trip before their own text appears.
    setPendingMessage(content);
    setActivity(THINKING);
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

      const pending: Promise<unknown>[] = [];
      await consumeSSE(response, (event) => {
        if (event.type === "user_message") {
          pending.push(loadSession().then(() => setPendingMessage(null)));
        } else if (event.type === "text_delta") {
          setActivity(null);
          setStreamingText((prev) => prev + ((event.delta as string) || ""));
        } else if (event.type === "tool_start") {
          setActivity((event.label as string) || "Working...");
        } else if (event.type === "done") {
          pending.push(loadSession(), loadPlans());
        }
      });
      await Promise.all(pending);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to send message");
    } finally {
      setSending(false);
      setStreamingText("");
      setActivity(null);
      setPendingMessage(null);
    }
  }

  async function deleteSession() {
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

  if (!session) return null;

  // The API returns newest-first, so the active plan is simply the first one.
  const activePlan = plans[0];

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
              onClick={() => setConfirmOpen(true)}
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
              <EmptyState>What do you want to learn?</EmptyState>
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
                  <div className="border border-white/10 px-4 py-3 text-sm">
                    {message.role === "assistant" ? (
                      <Markdown className="prose-p:my-0">{message.content}</Markdown>
                    ) : (
                      message.content
                    )}
                  </div>
                )}
              </div>
            ))}
            {pendingMessage && (
              <div className="self-end max-w-lg">
                <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">user</p>
                <div className="border border-white/10 px-4 py-3 text-sm">{pendingMessage}</div>
              </div>
            )}
            {activity && <ChatActivity label={activity} />}
            {streamingText && (
              <div className="self-start max-w-lg">
                <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">assistant</p>
                <div className="border border-white/10 px-4 py-3 text-sm">
                  <Markdown className="prose-p:my-0">{streamingText}</Markdown>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>
        <div className="flex-none px-10 py-6 border-t border-white/10 flex items-end gap-4">
          <Textarea
            ref={inputRef}
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Message..."
            // Grows from 1 line up to 3, then scrolls - see the autosize effect above.
            className="flex-1 resize-none min-h-0 py-2 overflow-y-auto leading-6"
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
