import { useEffect, useRef, useState } from "react";
import { CheckCircle2, RefreshCcw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GeminiKeyForm } from "@/components/GeminiKey";

interface HealthResponse {
  status: "ok" | "degraded";
  services: { citron: boolean; gemini: boolean };
}

// Fast while something is down (the user is watching and waiting), slow once everything
// is up - the check still runs for the whole session so a service dying mid-session is
// noticed, but at 30s it isn't hammering /health (and through it Citron) all day.
const POLL_DEGRADED_MS = 3000;
const POLL_HEALTHY_MS = 30000;

export function HealthGate({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  async function check() {
    setChecking(true);
    try {
      const response = await fetch("/health");
      const body = (await response.json()) as HealthResponse;
      setHealth(body);
    } catch {
      setHealth({ status: "degraded", services: { citron: false, gemini: false } });
    } finally {
      setChecking(false);
    }
  }

  // Polls for the whole session, not just until the first "ok" - otherwise a service that
  // dies mid-session is never noticed and every later request just fails.
  useEffect(() => {
    check();
  }, []);

  useEffect(() => {
    const interval = health?.status === "ok" ? POLL_HEALTHY_MS : POLL_DEGRADED_MS;
    timerRef.current = setInterval(check, interval);
    return () => clearInterval(timerRef.current);
  }, [health?.status]);

  // Blank until the first check resolves - rendering the gate optimistically flashes
  // "Waiting for services" on every page load before /health has even answered.
  if (health === null) return null;
  if (health.status === "ok") return <>{children}</>;

  const services: { key: keyof HealthResponse["services"]; label: string; hint: string }[] = [
    {
      key: "citron",
      label: "Citron sandbox",
      hint: "Citron unreachable - start the judge service and retry.",
    },
    { key: "gemini", label: "Gemini API key", hint: "No API key configured yet." },
  ];

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-black text-white px-6">
      <div className="w-full max-w-md space-y-6 text-center">
        <h1 className="text-2xl font-black uppercase tracking-tighter">Waiting for services</h1>
        <p className="text-xs text-zinc-500 uppercase tracking-widest">
          Tangerine needs these to be reachable before you can continue
        </p>
        <div className="space-y-2 text-left">
          {services.map(({ key, label, hint }) => {
            const ok = health?.services?.[key] ?? false;
            return (
              <div key={key} className="flex items-start gap-3 border border-white/10 px-4 py-3">
                {ok ? (
                  <CheckCircle2 className="w-4 h-4 text-green-500 flex-none mt-0.5" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-500 flex-none mt-0.5" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold">{label}</p>
                  {!ok && key === "gemini" ? (
                    <div className="mt-2 space-y-2">
                      <p className="text-xs text-zinc-500">
                        Paste a Gemini API key. It's verified against Google before it's
                        saved, then stored encrypted on this machine.
                      </p>
                      <GeminiKeyForm onSaved={check} />
                    </div>
                  ) : (
                    !ok && <p className="text-xs text-zinc-500 mt-0.5">{hint}</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <Button variant="outline" onClick={check} disabled={checking} className="text-[10px]">
          {checking ? <RefreshCcw className="mr-2 h-3.5 w-3.5 animate-spin" /> : null}
          Retry now
        </Button>
      </div>
    </div>
  );
}
