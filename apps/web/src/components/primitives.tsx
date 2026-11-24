export type Tone = "neutral" | "success" | "danger" | "warning" | "info";

const toneCls: Record<Tone, string> = {
  neutral: "bg-surface-high/70 text-muted",
  success: "bg-accent-soft text-primary",
  danger: "bg-danger-soft text-danger",
  warning: "bg-amber-50 text-amber-900",
  info: "bg-surface-low text-foreground/80",
};

/** Small status pill. The text is always present, so colour is never the only signal. */
export function StatusIndicator({
  tone,
  children,
  dot = true,
}: {
  tone: Tone;
  children: React.ReactNode;
  dot?: boolean;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[11px] tracking-[0.04em] ${toneCls[tone]}`}
    >
      {dot && (
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {children}
    </span>
  );
}

/** Empty or unavailable state. `testId` lets tests assert the honest state. */
export function EmptyState({
  title,
  children,
  icon,
  testId = "empty-state",
  action,
}: {
  title: string;
  children?: React.ReactNode;
  icon?: React.ReactNode;
  testId?: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      className="flex flex-col items-center rounded-2xl border border-dashed border-line bg-surface px-6 py-12 text-center"
    >
      {icon && (
        <div
          aria-hidden
          className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-surface-low text-muted"
        >
          {icon}
        </div>
      )}
      <h2 className="text-lg font-medium">{title}</h2>
      {children && (
        <div className="mt-1 max-w-md text-sm text-muted">{children}</div>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** White elevated container used for cards and panels. */
export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.03)] ${className}`}
    >
      {children}
    </div>
  );
}
