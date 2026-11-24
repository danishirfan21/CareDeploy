import Link from "next/link";

export const inputCls =
  "min-h-11 w-full rounded-lg border border-line bg-surface px-3 py-2 text-base outline-none focus:border-accent focus:ring-1 focus:ring-accent disabled:bg-surface-low md:text-sm";

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[28px] font-semibold leading-9 tracking-[-0.03em] md:text-4xl md:leading-[44px]">
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

const btn =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
export const primaryBtn = `${btn} bg-primary text-white hover:bg-primary-hover`;
export const secondaryBtn = `${btn} bg-surface-high/70 text-foreground hover:bg-surface-high`;

export function ButtonLink({
  href,
  children,
  variant = "primary",
}: {
  href: string;
  children: React.ReactNode;
  variant?: "primary" | "secondary";
}) {
  return (
    <Link
      href={href}
      className={variant === "primary" ? primaryBtn : secondaryBtn}
    >
      {children}
    </Link>
  );
}

export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {children}
      {hint && !error && (
        <span className="mt-1 block text-xs text-muted">{hint}</span>
      )}
      {error && (
        <span role="alert" className="mt-1 block text-xs text-danger">
          {error}
        </span>
      )}
    </label>
  );
}

export function Notice({
  tone,
  children,
}: {
  tone: "error" | "info" | "success" | "warning";
  children: React.ReactNode;
}) {
  const cls = {
    error: "border-danger/30 bg-danger-soft text-danger",
    info: "border-line bg-surface-low text-foreground/80",
    success: "border-accent/25 bg-accent-soft text-primary",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
  }[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-xl border px-4 py-3 text-sm ${cls}`}
    >
      {children}
    </div>
  );
}

export function Unavailable({
  title,
  milestone,
  children,
}: {
  title: string;
  milestone: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <PageHeader title={title} />
      <div data-testid="unavailable">
        <Notice tone="info">
          <strong className="font-medium">Not available yet.</strong> Planned
          for {milestone}. {children}
        </Notice>
      </div>
    </>
  );
}
