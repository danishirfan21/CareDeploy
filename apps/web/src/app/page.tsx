import Link from "next/link";
import { Icon, type IconName } from "@/components/icons";

const ACTIONS: { href: string; label: string; icon: IconName }[] = [
  { href: "/clinics/new", label: "Set up a clinic", icon: "building" },
  { href: "/playground", label: "Test a voice agent", icon: "playground" },
  { href: "/evaluations", label: "Run evaluations", icon: "evaluations" },
];

export default function Home() {
  return (
    <div className="flex min-h-[55vh] flex-col items-center justify-center text-center md:min-h-[60vh]">
      <div
        aria-hidden
        className="mb-6 flex h-11 w-11 items-center justify-center rounded-2xl border border-line bg-surface text-primary"
      >
        <Icon name="activity" className="h-6 w-6" />
      </div>
      <h1 className="text-[28px] font-semibold leading-9 tracking-[-0.03em] md:text-4xl md:leading-[44px]">
        What would you like to do?
      </h1>
      <p className="mx-auto mt-2 max-w-md text-muted">
        Set up a clinic, test an agent, or review recent activity.
      </p>
      <ul
        aria-label="Suggested actions"
        className="mt-10 flex flex-wrap items-center justify-center gap-3"
      >
        {ACTIONS.map((a) => (
          <li key={a.href}>
            <Link
              href={a.href}
              className="inline-flex min-h-11 items-center gap-2 rounded-full border border-line bg-surface px-5 text-sm hover:bg-surface-low"
            >
              <Icon name={a.icon} className="h-4 w-4 text-primary" />
              {a.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
