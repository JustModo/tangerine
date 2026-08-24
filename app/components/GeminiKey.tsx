import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch, apiJson } from "~/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SectionLabel } from "@/components/Section";

export interface GeminiKeyStatus {
  configured: boolean;
  source: "env" | "stored" | null;
  masked: string | null;
}

/** Key entry, shared by the startup gate and the landing-page settings panel. */
export function GeminiKeyForm({
  onSaved,
  submitLabel = "Verify",
}: {
  onSaved: () => void;
  submitLabel?: string;
}) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!apiKey.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const response = await apiFetch("/api/setup/gemini-key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim() }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.error ?? "Could not save that key.");
        return;
      }
      setApiKey("");
      onSaved();
    } catch {
      setError("Could not reach the agent.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && save()}
          placeholder="AIza..."
          className="flex-1 h-8 text-xs"
          autoComplete="off"
        />
        <Button size="sm" onClick={save} disabled={saving || !apiKey.trim()} className="text-[10px]">
          {saving ? <RefreshCcw className="mr-2 h-3 w-3 animate-spin" /> : null}
          {saving ? "Verifying" : submitLabel}
        </Button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

/** Landing-page panel: shows which key is in use and lets it be replaced or removed. */
export function GeminiKeySettings() {
  const [status, setStatus] = useState<GeminiKeyStatus | null>(null);
  const [removing, setRemoving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  async function load() {
    try {
      setStatus(await apiJson<GeminiKeyStatus>("/api/setup/gemini-key"));
    } catch {
      setStatus(null);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function remove() {
    if (removing) return;
    setConfirmOpen(false);
    setRemoving(true);
    try {
      setStatus(await apiJson<GeminiKeyStatus>("/api/setup/gemini-key", { method: "DELETE" }));
    } catch {
      // Leave the previous status on screen; the next load() will resync.
    } finally {
      setRemoving(false);
    }
  }

  const fromEnv = status?.source === "env";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <SectionLabel as="p">
            Gemini API key
          </SectionLabel>
          <p className="text-xs text-zinc-400 mt-1">
            {!status?.configured
              ? "Not configured."
              : fromEnv
                ? `Set by GEMINI_API_KEY in the environment (${status.masked}).`
                : `Stored on this machine (${status.masked}).`}
          </p>
        </div>
        {status?.configured && !fromEnv && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={removing}
            className="text-[10px] flex-none"
          >
            {removing ? <RefreshCcw className="mr-2 h-3 w-3 animate-spin" /> : null}
            Remove
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title="Remove the stored key?"
        body="Tangerine can't reach Gemini until you enter a key again."
        confirmLabel="Remove"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={remove}
      />
      {fromEnv ? (
        <p className="text-xs text-zinc-500">
          Environment keys take priority and can't be changed from here - edit the .env file
          instead.
        </p>
      ) : (
        <GeminiKeyForm onSaved={load} submitLabel={status?.configured ? "Replace" : "Verify"} />
      )}
    </div>
  );
}
