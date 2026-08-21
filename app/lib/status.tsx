import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";

interface StatusContextValue {
  error: string | null;
  showError: (message: string) => void;
  clearError: () => void;
  busyMessage: string | null;
  setBusyMessage: (message: string | null) => void;
}

const StatusContext = createContext<StatusContextValue | null>(null);

export function StatusProvider({ children }: { children: ReactNode }) {
  const [error, setError] = useState<string | null>(null);
  const [busyMessage, setBusyMessage] = useState<string | null>(null);

  const showError = useCallback((message: string) => setError(message), []);
  const clearError = useCallback(() => setError(null), []);

  return (
    <StatusContext.Provider value={{ error, showError, clearError, busyMessage, setBusyMessage }}>
      {children}
    </StatusContext.Provider>
  );
}

export function useStatus() {
  const ctx = useContext(StatusContext);
  if (!ctx) throw new Error("useStatus must be used within StatusProvider");
  return ctx;
}

export function ErrorBanner() {
  const { error, clearError } = useStatus();
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    clearTimeout(timerRef.current);
    if (error) {
      timerRef.current = setTimeout(clearError, 8000);
    }
    return () => clearTimeout(timerRef.current);
  }, [error, clearError]);

  if (!error) return null;

  return (
    <div className="w-full flex-none bg-red-600 text-white text-xs font-bold uppercase tracking-widest px-10 py-2 flex items-center justify-between gap-4">
      <span className="truncate">{error}</span>
      <button
        onClick={clearError}
        aria-label="Dismiss error"
        className="flex-none hover:opacity-70 transition-opacity"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export function BusyIndicator() {
  const { busyMessage } = useStatus();
  if (!busyMessage) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 bg-zinc-900 border border-white/10 text-white text-[10px] font-bold uppercase tracking-widest px-4 py-2 rounded-full flex items-center gap-2 shadow-lg">
      <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse flex-none" />
      {busyMessage}
    </div>
  );
}
