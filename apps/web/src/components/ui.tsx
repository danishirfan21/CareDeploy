import Link from "next/link";

export const inputCls =
  "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:bg-gray-50";

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
    <div className="mb-8 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

const btn =
  "inline-flex items-center justify-center rounded-lg px-3.5 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
export const primaryBtn = `${btn} bg-accent text-white hover:bg-teal-800`;
export const secondaryBtn = `${btn} border border-line bg-white hover:bg-gray-50`;

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
        <span role="alert" className="mt-1 block text-xs text-red-600">
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
    error: "border-red-200 bg-red-50 text-red-800",
    info: "border-line bg-gray-50 text-foreground/80",
    success: "border-teal-200 bg-accent-soft text-teal-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
  }[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg border px-4 py-3 text-sm ${cls}`}
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
