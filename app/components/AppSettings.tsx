import { useEffect, useState } from "react";
import { ApiError, apiJson } from "~/lib/api";
import { useStatus } from "~/lib/status";

interface SettingEntry {
  value: string;
  options: string[];
}

type SettingsShape = Record<string, SettingEntry>;

// Display label for a known preference key. A preference added to the backend registry
// without an entry here still renders — just with its key title-cased as a fallback.
const LABELS: Record<string, string> = {
  default_language: "Default learning language",
};

function labelFor(key: string): string {
  return LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function optionLabel(value: string): string {
  return value === "ask" ? "Ask" : value;
}

/** Renders one control per entry the backend's preference registry returns — a future
 * preference needs no frontend change at all to start appearing here. */
export function AppSettings() {
  const [settings, setSettings] = useState<SettingsShape | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const { showError } = useStatus();

  async function load() {
    try {
      setSettings(await apiJson<SettingsShape>("/api/settings"));
    } catch (err) {
      // Without this the panel just vanishes, which is indistinguishable from having no
      // settings at all.
      setSettings(null);
      showError(err instanceof ApiError ? err.message : "Couldn't load settings");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function update(key: string, value: string) {
    setSaving(key);
    try {
      setSettings(
        await apiJson<SettingsShape>("/api/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [key]: value }),
        }),
      );
    } catch (err) {
      // Previous value stays on screen; the next load() resyncs it.
      showError(err instanceof ApiError ? err.message : "Couldn't save that setting");
    } finally {
      setSaving(null);
    }
  }

  if (!settings || Object.keys(settings).length === 0) return null;

  return (
    <div className="flex flex-col divide-y divide-white/5 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
      {Object.entries(settings).map(([key, entry]) => (
        <div key={key} className="py-3 flex items-center justify-between gap-4">
          <p className="text-xs uppercase tracking-wide">{labelFor(key)}</p>
          <select
            value={entry.value}
            disabled={saving === key}
            onChange={(event) => update(key, event.target.value)}
            className="bg-zinc-950 border-l border-white/20 h-8 text-xs px-2 disabled:opacity-50"
          >
            {entry.options.map((option) => (
              <option key={option} value={option}>
                {optionLabel(option)}
              </option>
            ))}
          </select>
        </div>
      ))}
    </div>
  );
}
