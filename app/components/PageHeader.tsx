import { useNavigate } from "react-router";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export function PageHeader({
  title,
  subtitle,
  actions,
  backTo,
  showBack = true,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  /** Explicit destination for the back button - e.g. chat/plan always go home, the code
   * window always goes back to its plan. Falls back to browser history if omitted. */
  backTo?: string;
  showBack?: boolean;
}) {
  const navigate = useNavigate();

  return (
    <div className="flex-none w-full px-6 py-3 flex items-center justify-between gap-4 border-b border-white/10 bg-black">
      <div className="flex items-center gap-3 min-w-0">
        {showBack && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => (backTo ? navigate(backTo) : navigate(-1))}
            aria-label="Back"
            className="flex-none"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
        )}
        <div className="min-w-0">
          {title && <div className="text-sm font-bold uppercase tracking-wide truncate">{title}</div>}
          {subtitle && (
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 truncate">{subtitle}</div>
          )}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 flex-none">{actions}</div>}
    </div>
  );
}
