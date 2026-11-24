import Link from "next/link";

const ACTIONS = [
  {
    href: "/clinics/new",
    title: "Set up a clinic",
    body: "Create a clinic and walk through its five-step configuration.",
    note: null,
  },
  {
    href: "/playground",
    title: "Test a voice agent",
    body: "Try a clinic's agent against its published configuration.",
    note: "Unavailable until M3",
  },
  {
    href: "/evaluations",
    title: "Run evaluations",
    body: "Score an agent against automated scenarios.",
    note: "Unavailable until M4",
  },
];

export default function Home() {
  return (
    <div className="pt-6 md:pt-16">
      <h1 className="text-3xl font-semibold tracking-tight">
        What would you like to do?
      </h1>
      <p className="mt-2 text-muted">
        Deploy configuration-driven voice agents across clinics.
      </p>
      <ul className="mt-10 grid gap-3">
        {ACTIONS.map((a) => (
          <li key={a.href}>
            <Link
              href={a.href}
              className="block rounded-xl border border-line p-4 transition hover:border-accent hover:bg-accent-soft"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{a.title}</span>
                {a.note && (
                  <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-muted">
                    {a.note}
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-muted">{a.body}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
