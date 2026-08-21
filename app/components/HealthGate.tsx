import { useEffect, useRef, useState } from "react";
import { CheckCircle2, RefreshCcw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface HealthResponse {
  status: "ok" | "degraded";
  services: { citron: boolean; gemini: boolean };
}

const SERVICE_LABELS: Record<keyof HealthResponse["services"], { label: string; hint: string }> = {
  citron: { label: "Citron sandbox", hint: "Citron unreachable — start the judge service and retry." },
  gemini: { label: "Gemini API key", hint: "GEMINI_API_KEY not configured on the agent." },
};

const POLL_INTERVAL_MS = 3000;

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

  useEffect(() => {
    check();
    timerRef.current = setInterval(check, POLL_INTERVAL_MS);
    return () => clearInterval(timerRef.current);
  }, []);

  useEffect(() => {
    if (health?.status === "ok") clearInterval(timerRef.current);
  }, [health?.status]);

  if (health?.status === "ok") return <>{children}</>;

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-black text-white px-6">
      <div className="w-full max-w-md space-y-6 text-center">
        <h1 className="text-2xl font-black uppercase tracking-tighter">Waiting for services</h1>
        <p className="text-xs text-zinc-500 uppercase tracking-widest">
          Tangerine needs these to be reachable before you can continue
        </p>
        <div className="space-y-2 text-left">
          {(Object.keys(SERVICE_LABELS) as (keyof HealthResponse["services"])[]).map((key) => {
            const ok = health?.services?.[key] ?? false;
            const meta = SERVICE_LABELS[key];
            return (
              <div
                key={key}
                className="flex items-start gap-3 border border-white/10 rounded-md px-4 py-3"
              >
                {ok ? (
                  <CheckCircle2 className="w-4 h-4 text-green-500 flex-none mt-0.5" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-500 flex-none mt-0.5" />
                )}
                <div>
                  <p className="text-sm font-bold">{meta.label}</p>
                  {!ok && <p className="text-xs text-zinc-500 mt-0.5">{meta.hint}</p>}
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
