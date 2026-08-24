import { Loader2 } from "lucide-react";

/** What the assistant is doing right now. A tool call is not token-streamed, so a turn that
 * calls one produces no output at all until the work is done. */
export function ChatActivity({ label }: { label: string }) {
  return (
    <div className="self-start flex items-center gap-2 text-xs italic text-zinc-500 px-1">
      <Loader2 className="w-3 h-3 animate-spin flex-none" />
      {label}
    </div>
  );
}

export const THINKING = "Thinking...";
