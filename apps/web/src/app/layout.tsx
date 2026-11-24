import type { Metadata, Viewport } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Shell } from "@/components/shell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const mono = JetBrains_Mono({
  variable: "--font-mono-face",
  subsets: ["latin"],
});

export const viewport: Viewport = { viewportFit: "cover" };

export const metadata: Metadata = {
  title: "CareDeploy",
  description: "Multi-clinic voice-agent deployment platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
