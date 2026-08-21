import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ListTree, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";

interface SessionSummary {
  id: string;
  status: string;
  updated_at: string;
  messages: { content: string }[];
}

interface LessonPlanSummary {
  id: string;
  topic: string;
}

export default function Home() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [plansBySession, setPlansBySession] = useState<Record<string, LessonPlanSummary | undefined>>({});
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { showError, setBusyMessage } = useStatus();

  async function loadSessions() {
    try {
      const data = await apiJson<SessionSummary[]>("/api/sessions");
      setSessions(data);
      // One lookup per session to know whether it already has a plan — a session with a
      // plan should lead with "continue learning", not "continue chat".
      const entries = await Promise.all(
        data.map(async (session) => {
          try {
            const plans = await apiJson<LessonPlanSummary[]>(
              `/api/learning-plans?session_id=${session.id}`,
            );
            // The API returns newest-first, so the active plan is simply the first one.
            return [session.id, plans[0]] as const;
          } catch {
            return [session.id, undefined] as const;
          }
        }),
      );
      setPlansBySession(Object.fromEntries(entries));
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

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full">
      <div className="flex-none w-full px-6 py-3 flex items-center justify-between gap-4 border-b border-white/10 bg-black">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.5em] text-zinc-500">Tangerine</p>
          <p className="text-sm font-bold uppercase tracking-wide">Learning Sessions</p>
        </div>
        <Button size="sm" className="tracking-[0.3em]" onClick={startNewSession}>
          + NEW SESSION
        </Button>
      </div>

      <ScrollArea className="flex-1 min-h-0 px-10">
        <div className="max-w-3xl mx-auto w-full flex flex-col pb-16">
          <div className="flex flex-col divide-y divide-white/5">
            {loading && (
              <p className="text-zinc-500 text-xs uppercase py-8 text-center">Loading...</p>
            )}
            {!loading && sessions.length === 0 && (
              <p className="text-zinc-500 text-xs uppercase py-8 text-center">
                No sessions yet. Start one above.
              </p>
            )}
            {sessions.map((session) => {
              const plan = plansBySession[session.id];
              const primaryTo = plan ? `/plans/${plan.id}` : `/sessions/${session.id}`;
              return (
                <Link
                  key={session.id}
                  to={primaryTo}
                  className="py-6 flex items-center justify-between gap-4 hover:bg-zinc-950 transition-colors px-4 group"
                >
                  <div className="space-y-1.5 min-w-0">
                    <p className="text-sm font-bold uppercase tracking-wide truncate">
                      {plan?.topic || session.messages[0]?.content || "Untitled session"}
                    </p>
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">
                      {session.status} · updated {new Date(session.updated_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-none text-zinc-500 group-hover:text-white transition-colors">
                    {plan ? <ListTree className="w-4 h-4" /> : <MessageSquare className="w-4 h-4" />}
                    <span className="text-xs uppercase tracking-widest">Continue</span>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
