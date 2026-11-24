/** Small stroke icon set (inline SVG, no icon font), shared by the shell and pages. */
const PATHS = {
  clinics: "M4 21V8l8-5 8 5v13M9 21v-6h6v6",
  playground:
    "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  activity: "M12 7v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4",
  evaluations:
    "M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "M6 6l12 12M18 6L6 18",
  panel: "M4 5h16v14H4zM9 5v14",
  plus: "M12 5v14M5 12h14",
  arrowRight: "M5 12h14M13 6l6 6-6 6",
  arrowLeft: "M19 12H5M11 6l-6 6 6 6",
  chevronDown: "M6 9l6 6 6-6",
  check: "M5 13l4 4L19 7",
  checkCircle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12l3 3 5-6",
  alertCircle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v5M12 16v.5",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  phone:
    "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
  phoneOff: "M3 3l18 18M5 4h4l2 5-2.5 1.5M15 13l5 2v4a2 2 0 0 1-2 2",
  wrench:
    "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z",
  transcript: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  play: "M7 5l12 7-12 7z",
  building: "M4 21V4h10v17M14 9h6v12M8 8h2M8 12h2M8 16h2M3 21h18",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  className = "h-5 w-5",
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`${className} shrink-0`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
