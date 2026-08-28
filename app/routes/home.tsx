import { useEffect, useState } from "react";
import type { MetaFunction } from "react-router";
import { Link, useLoaderData, useNavigate } from "react-router";
import { BarChart3, Download, DownloadCloud, ListTree, MessageSquare, RefreshCw, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useStatus } from "~/lib/status";
import { ApiError, apiJson } from "~/lib/api";
import { GeminiKeySettings } from "@/components/GeminiKey";
import { AppSettings } from "@/components/AppSettings";
import { Separator } from "@/components/ui/separator";
import { EmptyState, SectionLabel } from "@/components/Section";

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

export const meta: MetaFunction = () => [
  { title: "Learning Sessions · Tangerine" },
  { name: "description", content: "Your Tangerine sessions. Start a new one, or pick up a plan you are partway through." },
];

const OUTDATED_CACHE_KEY = "tangerine:outdated-check";
const OUTDATED_CACHE_TTL_MS = 60 * 60 * 1000; // recheck GitHub at most once an hour

export async function clientLoader() {
  const sessions = await apiJson<SessionSummary[]>("/api/sessions");
  // One lookup per session to know whether it already has a plan - a session with a plan
  // should lead with "continue learning", not "continue chat".
  const entries = await Promise.all(
    sessions.map(async (session) => {
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
  return { sessions, plansBySession: Object.fromEntries(entries) };
}


async function checkOutdated(): Promise<boolean> {
  try {
    const cached = localStorage.getItem(OUTDATED_CACHE_KEY);
    if (cached) {
      const { outdated, checkedAt } = JSON.parse(cached);
      if (Date.now() - checkedAt < OUTDATED_CACHE_TTL_MS) return outdated;
    }

    const [health, latest] = await Promise.all([
      apiJson<{ git_sha: string }>("/health"),
      fetch("https://api.github.com/repos/JustModo/tangerine/commits/master").then((r) => r.json()),
    ]);
    const outdated = health.git_sha !== "unknown" && !latest.sha?.startsWith(health.git_sha);
    localStorage.setItem(OUTDATED_CACHE_KEY, JSON.stringify({ outdated, checkedAt: Date.now() }));
    return outdated;
  } catch {
    // Offline, rate-limited, or dev mode without a built image - just stay quiet.
    return false;
  }
}

export default function Home() {
  const { sessions, plansBySession } = useLoaderData<typeof clientLoader>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [outdated, setOutdated] = useState(false);
  const navigate = useNavigate();
  const { showError, setBusyMessage } = useStatus();

  useEffect(() => {
    checkOutdated().then(setOutdated);
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
      {outdated && (
        <a
          href="https://github.com/JustModo/tangerine"
          target="_blank"
          rel="noopener noreferrer"
          title="A newer version is available on GitHub, pull and rebuild to update"
          className="fixed bottom-6 left-6 z-50 text-amber-500 hover:text-amber-400"
        >
          <DownloadCloud className="w-4 h-4" />
        </a>
      )}
      <div className="flex-none w-full px-6 py-3 flex items-center justify-between gap-4 border-b border-white/10 bg-black">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.5em] text-zinc-500">Tangerine</p>
          <p className="text-sm font-bold uppercase tracking-wide">Learning Sessions</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Progress"
            onClick={() => navigate("/progress")}
            className="text-zinc-500 hover:text-white"
          >
            <BarChart3 className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Settings"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((open) => !open)}
            className={settingsOpen ? "text-white" : "text-zinc-500 hover:text-white"}
          >
            <Settings className="w-4 h-4" />
          </Button>
          <Button size="sm" className="tracking-[0.3em]" onClick={startNewSession}>
            + NEW SESSION
          </Button>
        </div>
      </div>

      {settingsOpen && (
        <div className="flex-none w-full border-b border-white/10 bg-zinc-950 px-10 py-5">
          <div className="max-w-3xl mx-auto w-full space-y-5">
            <div>
              <SectionLabel as="p" className="mb-3">
                Gemini
              </SectionLabel>
              <Separator className="bg-white/10 mb-4" />
              <GeminiKeySettings />
            </div>
            <div>
              <SectionLabel as="p" className="mb-3">
                Preferences
              </SectionLabel>
              <Separator className="bg-white/10 mb-4" />
              <AppSettings />
            </div>
          </div>
        </div>
      )}

      <ScrollArea className="flex-1 min-h-0 px-10">
        <div className="max-w-3xl mx-auto w-full flex flex-col pb-16">
          <div className="flex flex-col divide-y divide-white/5">
            {sessions.length === 0 && (
              <EmptyState>No sessions yet. Start one above.</EmptyState>
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
