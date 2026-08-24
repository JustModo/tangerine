/** The app's one heading style, and the empty-state that goes with it.
 *
 * Both were copy-pasted class strings before — 13 headings and 5 empty states — and two of
 * the empty states had already drifted apart from the rest.
 */

export function SectionLabel({
  children,
  as: Tag = "h3",
  className = "",
}: {
  children: React.ReactNode;
  as?: "h2" | "h3" | "p";
  className?: string;
}) {
  return (
    <Tag className={`text-[10px] font-black uppercase tracking-[0.3em] text-zinc-500 ${className}`}>
      {children}
    </Tag>
  );
}

export function Section({
  title,
  children,
  as,
}: {
  title: string;
  children: React.ReactNode;
  as?: "h2" | "h3";
}) {
  return (
    <div className="space-y-3">
      <SectionLabel as={as ?? "h2"}>{title}</SectionLabel>
      {children}
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-zinc-500 text-xs uppercase tracking-widest py-8 text-center">{children}</p>
  );
}
