import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import "./globals.css";

/**
 * Typography: Inter / Inter, matched by ui-ux-pro-max typography search —
 * mood "dark, cinematic, technical, precision, premium", best for "AI
 * dashboards, high-end productivity apps". Mono is added for tabular
 * financial figures, where proportional digits would jitter as values update.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Onboarding Agent",
  description:
    "Human-gated onboarding workflow driven by a LangGraph multi-agent system.",
};

export const viewport: Viewport = {
  themeColor: "#07090C",
  // Zoom is never disabled — ui-ux-pro-max §5 lists "Disable zoom" as an
  // anti-pattern and it is a WCAG 1.4.4 failure.
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-dvh bg-void font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-signal focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-on-primary"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
