import type { Config } from "tailwindcss";

/**
 * Tokens mirror the CSS custom properties in app/globals.css.
 * Components reference semantic names only — never raw hex.
 * (ui-ux-pro-max §6: "Raw hex in components" is a listed anti-pattern.)
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "rgb(var(--c-void) / <alpha-value>)",
        abyss: "rgb(var(--c-abyss) / <alpha-value>)",
        fg: "rgb(var(--c-fg) / <alpha-value>)",
        "fg-muted": "rgb(var(--c-fg-muted) / <alpha-value>)",
        "fg-faint": "rgb(var(--c-fg-faint) / <alpha-value>)",
        signal: "rgb(var(--c-signal) / <alpha-value>)",
        "signal-deep": "rgb(var(--c-signal-deep) / <alpha-value>)",
        hold: "rgb(var(--c-hold) / <alpha-value>)",
        settled: "rgb(var(--c-settled) / <alpha-value>)",
        alarm: "rgb(var(--c-alarm) / <alpha-value>)",
        violet: "rgb(var(--c-violet) / <alpha-value>)",
        "violet-deep": "rgb(var(--c-violet-deep) / <alpha-value>)",
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--c-surface-raised) / <alpha-value>)",
        "on-primary": "rgb(var(--c-on-primary) / <alpha-value>)",
        // Neutral fills as alpha over whatever is beneath, so a component no
        // longer has to know whether the ground is light or dark.
        fill: "var(--fill)",
        "fill-strong": "var(--fill-strong)",
        line: "var(--line)",
        "line-soft": "var(--line-soft)",
        "line-strong": "var(--line-strong)",
      },
      // Named sizes so components stop hard-coding text-[11px] and the scale
      // can be retuned in one place.
      fontSize: {
        micro: ["var(--t-micro)", { lineHeight: "1.45" }],
        body: ["var(--t-body)", { lineHeight: "1.55" }],
        base: ["var(--t-base)", { lineHeight: "1.55" }],
        lead: ["var(--t-lead)", { lineHeight: "1.4", letterSpacing: "-0.01em" }],
        title: ["var(--t-title)", { lineHeight: "1.25", letterSpacing: "-0.02em" }],
        display: ["var(--t-display)", { lineHeight: "1.1", letterSpacing: "-0.03em" }],
      },
      divideColor: {
        line: "var(--line)",
        "line-soft": "var(--line-soft)",
      },
      spacing: {
        sidebar: "var(--sidebar-w)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        lift: "var(--shadow-lift)",
      },
      borderRadius: {
        card: "var(--radius-card)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      transitionTimingFunction: {
        // Shared motion tokens — ux-guidelines "Duration Timing" warns against
        // copying one duration/easing to every transition.
        swift: "cubic-bezier(0.22, 1, 0.36, 1)",
        settle: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      keyframes: {
        breathe: {
          "0%, 100%": { opacity: "0.45", transform: "scale(1)" },
          "50%": { opacity: "0.9", transform: "scale(1.06)" },
        },
        "scan-line": {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(400%)" },
        },
        "trace-in": {
          "0%": { strokeDashoffset: "1" },
          "100%": { strokeDashoffset: "0" },
        },
        // Transform/opacity only — animating position or size here would
        // force layout on a full-viewport element every frame.
        drift: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%": { transform: "translate3d(6%, 4%, 0) scale(1.08)" },
        },
      },
      animation: {
        breathe: "breathe 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scan-line": "scan-line 7s linear infinite",
        drift: "drift 26s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
