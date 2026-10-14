"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { LogoMark } from "@/components/brand/Logo";
import {
  IconArrowLeft, IconLayers, IconMail, IconPlus, IconPulse, IconShield, IconX,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import { clearSession, getSession } from "@/lib/session";

/**
 * Persistent shell for the HR console.
 *
 * Replaces the single long scroll. Previously every surface — metrics,
 * queues, correspondence, calls — was a glass card stacked on the same page,
 * which meant navigating meant scrolling and nothing could be deep-linked.
 * Each destination is now its own route, so the back button and a pasted URL
 * both work.
 *
 * The nav is real <Link>s, not client-side view state: a tab control would
 * have been less code but would have put four views behind one URL.
 */

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

const NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: <IconLayers className="h-4 w-4" /> },
  { href: "/threads", label: "Candidates", icon: <IconShield className="h-4 w-4" /> },
  { href: "/mail", label: "Correspondence", icon: <IconMail className="h-4 w-4" /> },
  { href: "/calls", label: "Voice calls", icon: <IconPulse className="h-4 w-4" /> },
  { href: "/reports", label: "Reports", icon: <IconLayers className="h-4 w-4" /> },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="space-y-0.5" aria-label="Sections">
      {NAV.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-[38px] items-center gap-2.5 rounded-lg px-2.5 text-body transition-colors duration-[--t-hover] ${
              active
                ? "bg-surface font-medium text-fg shadow-card"
                : "text-fg-muted hover:bg-fill hover:text-fg"
            }`}
          >
            <span className={active ? "text-signal" : "text-fg-faint"}>
              {item.icon}
            </span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const session = getSession();
  return (
    <div className="flex h-full flex-col">
      <Link
        href="/"
        onClick={onNavigate}
        className="group/logo flex items-center gap-2.5 px-2.5 py-1"
      >
        <LogoMark className="h-7 w-7 shrink-0 text-fg" interactive={false} />
        <span className="min-w-0 leading-tight">
          <span className="block truncate text-base font-semibold tracking-[-0.01em] text-fg">
            Aperture
          </span>
          <span className="block truncate text-micro text-fg-muted">
            Onboarding Control
          </span>
        </span>
      </Link>

      <div className="mt-5 flex-1">
        <NavLinks onNavigate={onNavigate} />
      </div>

      <div className="space-y-2 border-t border-line-soft pt-3">
        <Link
          href="/onboard"
          onClick={onNavigate}
          className="flex min-h-[38px] items-center justify-center gap-1.5 rounded-lg bg-signal px-3 text-body font-semibold text-on-primary transition-colors duration-[--t-hover] hover:bg-signal/90"
        >
          <IconPlus className="h-4 w-4" />
          Onboard
        </Link>

        <div className="flex items-center justify-between gap-2 px-1">
          <span className="min-w-0 truncate text-micro text-fg-muted">
            {session?.username ? `Signed in as ${session.username}` : "Not signed in"}
          </span>
          <button
            type="button"
            onClick={() => { void api.logout().catch(() => {}); clearSession(); }}
            className="-my-2.5 inline-flex min-h-[44px] shrink-0 cursor-pointer items-center rounded px-1 text-micro text-fg-muted underline-offset-2 hover:text-fg hover:underline"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}

export function AppShell({
  title,
  subtitle,
  back,
  actions,
  children,
}: {
  title: string;
  /** Context line under the title — role, department, email on a detail page. */
  subtitle?: React.ReactNode;
  /** Detail pages keep an explicit way back even though the rail is always there. */
  back?: { href: string; label: string };
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="page-wash min-h-dvh">
      {/* Desktop rail. Fixed so long content scrolls under a stationary nav. */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-sidebar border-r border-line-soft p-3 lg:block">
        <SidebarBody />
      </aside>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-void/80"
            onClick={() => setMenuOpen(false)}
            aria-hidden="true"
          />
          <aside className="absolute inset-y-0 left-0 w-[260px] border-r border-line-soft bg-void p-3">
            <SidebarBody onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-sidebar">
        <header className="sticky top-0 z-20 flex min-h-[56px] flex-wrap items-center gap-x-3 gap-y-2 border-b border-line-soft bg-void/80 px-4 py-2.5 backdrop-blur-md sm:px-6">
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            className="-ml-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-fg-muted hover:bg-fill-strong hover:text-fg lg:hidden"
          >
            {menuOpen ? (
              <IconX className="h-4.5 w-4.5" />
            ) : (
              <span aria-hidden="true" className="space-y-[3px]">
                <span className="block h-px w-4 bg-current" />
                <span className="block h-px w-4 bg-current" />
                <span className="block h-px w-4 bg-current" />
              </span>
            )}
          </button>

          <div className="min-w-0 flex-1">
            {back && (
              <Link
                href={back.href}
                className="group -my-3 -ml-1 inline-flex min-h-[44px] items-center gap-1 rounded px-1 text-micro text-fg-muted transition-colors duration-[--t-hover] hover:text-fg"
              >
                <IconArrowLeft className="h-3 w-3 transition-transform duration-[--t-hover] group-hover:-translate-x-0.5" />
                {back.label}
              </Link>
            )}
            <h1 className="truncate text-lead font-semibold text-fg">{title}</h1>
            {subtitle && (
              <p className="truncate text-micro text-fg-muted">{subtitle}</p>
            )}
          </div>

          {actions}
        </header>

        <main id="main" tabIndex={-1} className="px-4 py-5 sm:px-6 sm:py-6">
          <div className="mx-auto w-full max-w-[1180px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
