import { notFound } from "next/navigation";
import type { ReactNode } from "react";

/**
 * The /dev pages are development and test tools. In a production build they answer 404 unless
 * NEXT_PUBLIC_ENABLE_DEV_PAGES=1 is set at build time, so they cannot be exposed by accident.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (
    process.env.NODE_ENV === "production" &&
    process.env.NEXT_PUBLIC_ENABLE_DEV_PAGES !== "1"
  ) {
    notFound();
  }
  return <>{children}</>;
}
