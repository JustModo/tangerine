import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";

/**
 * Replaces window.confirm() for destructive actions. The native dialog blocks the whole
 * thread, ignores the app's design system and can't be driven from a test.
 *
 * Built on <dialog> rather than a modal library: the platform already gives focus
 * trapping, Escape-to-close and the top-layer backdrop for free.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Delete",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body?: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      className="m-auto bg-transparent p-0 backdrop:bg-black/70 max-w-md w-[calc(100%-2rem)]"
    >
      <div className="bg-zinc-950 border border-white/15 rounded-md p-6 space-y-4 text-white">
        <div className="space-y-1.5">
          <h2 className="text-sm font-bold uppercase tracking-wide">{title}</h2>
          {body && <p className="text-xs text-zinc-400">{body}</p>}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} className="text-[10px]">
            Cancel
          </Button>
          <Button size="sm" onClick={onConfirm} className="text-[10px]">
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
