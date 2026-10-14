/**
 * Inline SVG icon set (Lucide-derived geometry).
 * ui-ux-pro-max §4 anti-pattern: "Emoji as icons" — none used anywhere.
 *
 * Every icon is decorative by default (aria-hidden) because each one sits
 * beside a real text label. An icon that ever stands alone must be given an
 * accessible name by its parent control.
 */
interface IconProps {
  className?: string;
  strokeWidth?: number;
}

const base = (className?: string) => ({
  className: className ?? "h-4 w-4",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false as const,
});

export const IconUser = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);

export const IconBranch = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <line x1="6" y1="3" x2="6" y2="15" />
    <circle cx="18" cy="6" r="3" />
    <circle cx="6" cy="18" r="3" />
    <path d="M18 9a9 9 0 0 1-9 9" />
  </svg>
);

export const IconBriefcase = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <rect x="2" y="7" width="20" height="14" rx="2" />
    <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
  </svg>
);

export const IconCoins = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <circle cx="8" cy="8" r="6" />
    <path d="M18.09 10.37A6 6 0 1 1 10.34 18" />
    <path d="M7 6h1v4" />
    <path d="m16.71 13.88.7.71-2.82 2.82" />
  </svg>
);

export const IconSend = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M22 2 11 13" />
    <path d="M22 2 15 22l-4-9-9-4Z" />
  </svg>
);

export const IconCheck = ({ className, strokeWidth = 2 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

export const IconX = ({ className, strokeWidth = 2 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);

export const IconAlert = ({ className, strokeWidth = 1.7 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </svg>
);

export const IconClock = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);

export const IconArrowRight = ({ className, strokeWidth = 1.8 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);

export const IconArrowLeft = ({ className, strokeWidth = 1.8 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M19 12H5M12 19l-7-7 7-7" />
  </svg>
);

export const IconSpinner = ({ className }: IconProps) => (
  <svg
    className={className ?? "h-4 w-4"}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" opacity="0.22" />
    <path
      d="M21 12a9 9 0 0 0-9-9"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);

export const IconPulse = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M3 12h4l3-8 4 16 3-8h4" />
  </svg>
);

export const IconShield = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
  </svg>
);

export const IconMail = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <path d="m22 7-10 6L2 7" />
  </svg>
);

export const IconPlus = ({ className, strokeWidth = 2 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const IconLock = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <rect x="3" y="11" width="18" height="11" rx="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

export const IconLayers = ({ className, strokeWidth = 1.6 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="m12 2 9 5-9 5-9-5 9-5Z" />
    <path d="m3 17 9 5 9-5M3 12l9 5 9-5" />
  </svg>
);

export const IconSearch = ({ className, strokeWidth = 1.7 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export const IconChevronRight = ({ className, strokeWidth = 2 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="m9 18 6-6-6-6" />
  </svg>
);

export const IconRefresh = ({ className, strokeWidth = 1.7 }: IconProps) => (
  <svg {...base(className)} strokeWidth={strokeWidth}>
    <path d="M21 12a9 9 0 1 1-2.64-6.36" />
    <path d="M21 3v6h-6" />
  </svg>
);
