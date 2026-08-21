import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";

interface SessionSummary {
  id: string;
  status: string;
  updated_at: string;
  messages: { content: string }[];
}

export default function Home() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { showError, setBusyMessage } = useStatus();

  async function loadSessions() {
    try {
      setSessions(await apiJson<SessionSummary[]>("/api/sessions"));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startNewSession() {
    setBusyMessage("Creating session...");
    try {
      const session = await apiJson<{ id: string }>("/api/sessions", { method: "POST" });
      navigate(`/sessions/${session.id}`);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to start a new session");
    } finally {
      setBusyMessage(null);
    }
  }

  async function deleteSession(e: React.MouseEvent, sessionId: string) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("Delete this session? This can't be undone.")) return;
    setBusyMessage("Deleting session...");
    try {
      await apiJson(`/api/sessions/${sessionId}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Failed to delete session");
    } finally {
      setBusyMessage(null);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full">
      <div className="max-w-3xl mx-auto w-full flex-none flex flex-col gap-10 px-10 pt-20 pb-10">
        <div className="space-y-4 text-center">
          <h1 className="text-7xl font-black tracking-tighter uppercase leading-none">
            Learning<br />Sessions
          </h1>
          <p className="text-zinc-500 text-sm font-bold uppercase tracking-[0.5em]">Tangerine Engine v1.0</p>
        </div>

        <Button className="tracking-[0.3em]" onClick={startNewSession}>
          + NEW SESSION
        </Button>
      </div>

      <ScrollArea className="flex-1 min-h-0 px-10">
        <div className="max-w-3xl mx-auto w-full flex flex-col gap-16 pb-16">
          <div className="flex flex-col divide-y divide-white/5 border-t border-white/5">
            {loading && (
              <p className="text-zinc-500 text-xs uppercase py-8 text-center">Loading...</p>
            )}
            {!loading && sessions.length === 0 && (
              <p className="text-zinc-500 text-xs uppercase py-8 text-center">
                No sessions yet. Start one above.
              </p>
            )}
            {sessions.map((session) => (
              <Link
                key={session.id}
                to={`/sessions/${session.id}`}
                className="py-6 flex items-center justify-between hover:bg-zinc-950 transition-colors px-4 group"
              >
                <div className="space-y-1 min-w-0">
                  <p className="text-sm font-bold uppercase tracking-wide truncate">
                    {session.messages[0]?.content || "Untitled session"}
                  </p>
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">
                    {session.status} · updated {new Date(session.updated_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-none">
                  <span className="text-xs uppercase tracking-widest text-zinc-500">Continue →</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-500 hover:bg-red-950/30"
                    onClick={(e) => deleteSession(e, session.id)}
                    aria-label="Delete session"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </Link>
            ))}
          </div>

          <div className="flex justify-center flex-col items-center gap-10 opacity-30">
            <Separator className="w-32 bg-white/20" />
            <Link to="/run" className="text-[10px] font-black uppercase tracking-[1em] hover:text-white">
              Test Runner
            </Link>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
