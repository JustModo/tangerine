import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Markdown } from "@/components/Markdown";
import { ChatActivity, THINKING } from "@/components/ChatActivity";
import { ApiError, apiFetch, apiJson, consumeSSE } from "~/lib/api";
import type { HelperContext, ProblemChatMessage } from "~/lib/types";

/**
 * Code review chat for one problem. The learner's code and last test run are read at send
 * time through getContext() rather than passed as props - otherwise every keystroke in the
 * editor would re-render this panel and its markdown.
 */
export function CodeHelperPanel({
  problemSessionId,
  getContext,
  onFirstMessage,
}: {
  problemSessionId: string;
  getContext: () => HelperContext;
  /** Fires once, on the first question asked - a solution reached with the helper's help
   * is weaker evidence of mastery than one reached without it. */
  onFirstMessage?: () => void;
}) {
  const [messages, setMessages] = useState<ProblemChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function loadMessages() {
    try {
      setMessages(await apiJson<ProblemChatMessage[]>(`/api/problem-sessions/${problemSessionId}/chat`));
    } catch {
      // Non-critical - an empty history just means starting fresh.
    }
  }

  useEffect(() => {
    loadMessages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemSessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, streamingText]);

  async function send() {
    if (!draft.trim() || sending) return;
    onFirstMessage?.();
    const content = draft;
    setDraft("");
    setSending(true);
    setStreamingText("");
    setError(null);
    try {
      const { source_code, last_run } = getContext();
      const response = await apiFetch(`/api/problem-sessions/${problemSessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, source_code, last_run }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.error ?? "The helper is unavailable right now.");
        return;
      }

      const pending: Promise<unknown>[] = [];
      await consumeSSE(response, (event) => {
        if (event.type === "text_delta") {
          setStreamingText((p) => p + ((event.delta as string) || ""));
        } else if (event.type === "user_message" || event.type === "done") {
          pending.push(loadMessages());
        }
      });
      await Promise.all(pending);
    } catch (err) {
      // A stream that ends without a reply must say so - silence reads as the helper
      // choosing to ignore the question.
      setError(err instanceof ApiError ? err.message : "The helper couldn't reply.");
      await loadMessages();
    } finally {
      setSending(false);
      setStreamingText("");
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* overflow-x-hidden: setting overflow-y makes the other axis compute to auto. */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden space-y-4 pr-1">
        {messages.map((message) => (
          <div key={message.id} className="min-w-0">
            <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">
              {message.role}
            </p>
            {message.role === "assistant" ? (
              <Markdown className="prose-p:my-1">{message.content}</Markdown>
            ) : (
              <p className="text-sm text-zinc-300 whitespace-pre-wrap">{message.content}</p>
            )}
          </div>
        ))}
        {streamingText && (
          <div>
            <p className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">assistant</p>
            <Markdown className="prose-p:my-1">{streamingText}</Markdown>
          </div>
        )}
        {error && (
          <p className="text-xs text-red-400 border border-red-500/30 px-3 py-2">
            {error}
          </p>
        )}
        {sending && !streamingText && <ChatActivity label={THINKING} />}
        <div ref={bottomRef} />
      </div>
      <div className="flex-none pt-3 flex items-end gap-2 border-t border-white/10">
        <Textarea
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about your code..."
          className="flex-1 resize-none min-h-0 py-2 text-sm leading-6"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <Button size="sm" onClick={send} disabled={sending}>
          ASK
        </Button>
      </div>
    </div>
  );
}
