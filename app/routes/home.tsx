import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

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

  useEffect(() => {
    fetch("/api/sessions")
      .then((res) => res.json())
      .then(setSessions)
      .catch(() => toast.error("Failed to load sessions"))
      .finally(() => setLoading(false));
  }, []);

  async function startNewSession() {
    try {
      const res = await fetch("/api/sessions", { method: "POST" });
      const session = await res.json();
      navigate(`/sessions/${session.id}`);
    } catch {
      toast.error("Failed to start a new session");
    }
  }

  return (
    <div className="flex-1 overflow-y-auto w-full">
      <div className="max-w-3xl mx-auto flex flex-col gap-16 py-20 px-10">
        <div className="space-y-4 text-center">
          <h1 className="text-7xl font-black tracking-tighter uppercase leading-none">
            Learning<br />Sessions
          </h1>
          <p className="text-zinc-500 text-sm font-bold uppercase tracking-[0.5em]">Tangerine Engine v1.0</p>
        </div>

        <Button className="h-14 text-xs tracking-[0.3em]" onClick={startNewSession}>
          + NEW SESSION
        </Button>

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
              className="py-6 flex items-center justify-between hover:bg-zinc-950 transition-colors px-4"
            >
              <div className="space-y-1">
                <p className="text-sm font-bold uppercase tracking-wide">
                  {session.messages[0]?.content || "Untitled session"}
                </p>
                <p className="text-zinc-500 text-[10px] uppercase tracking-widest">
                  {session.status} · updated {new Date(session.updated_at).toLocaleString()}
                </p>
              </div>
              <span className="text-xs uppercase tracking-widest text-zinc-500">Continue →</span>
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
    </div>
  );
}
