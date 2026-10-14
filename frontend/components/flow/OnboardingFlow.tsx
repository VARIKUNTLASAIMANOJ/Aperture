"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/Button";
import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  IconArrowLeft, IconArrowRight, IconBranch, IconBriefcase,
  IconCoins, IconSend, IconUser,
} from "@/components/ui/Icons";
import { StepProgress } from "@/components/ui/StepProgress";
import { api } from "@/lib/api";
import {
  AGENT_PROFILES, MOOD_CAPTION, decisionTint, moodFromBackend,
  type AgentMood,
} from "@/lib/agentState";
import {
  emptyDraft, toTriggerRequest, validateStep,
  type Draft, type Errors,
} from "@/lib/form";
import { fieldStagger, stepVariants, T } from "@/lib/motion";
import type { OnboardingStateResponse, StreamEvent } from "@/lib/types";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { BackendStatus } from "./BackendStatus";
import { LiveRun } from "./LiveRun";
import { CompensationStep } from "./steps/CompensationStep";
import { DecisionStep } from "./steps/DecisionStep";
import { EngagementStep } from "./steps/EngagementStep";
import { IdentityStep } from "./steps/IdentityStep";
import { ReviewStep } from "./steps/ReviewStep";

type StepId = "identity" | "decision" | "engagement" | "compensation" | "review";

const STEP_META: Record<
  StepId,
  { label: string; title: string; blurb: string; Icon: typeof IconUser; mood: AgentMood }
> = {
  identity: {
    label: "Candidate", title: "Who are we onboarding?",
    blurb: "Identity and reporting line. These fields drive every downstream document.",
    Icon: IconUser, mood: "attentive",
  },
  decision: {
    label: "Decision", title: "Which way does this go?",
    blurb: "This choice forks the graph. Everything after it differs.",
    Icon: IconBranch, mood: "deciding",
  },
  engagement: {
    label: "Engagement", title: "Shape of the engagement",
    blurb: "Employment type and dates determine tax treatment and leave accrual.",
    Icon: IconBriefcase, mood: "attentive",
  },
  compensation: {
    label: "Compensation", title: "What are we paying?",
    blurb: "Figures are computed by deterministic Python — no model touches the maths.",
    Icon: IconCoins, mood: "computing",
  },
  review: {
    label: "Dispatch", title: "Ready to hand off",
    blurb: "Review the payload, then release it to the agent graph.",
    Icon: IconSend, mood: "drafting",
  },
};

export function OnboardingFlow() {
  const reduced = useReducedMotion();
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [errors, setErrors] = useState<Errors>({});
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState(1);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [backendState, setBackendState] = useState<OnboardingStateResponse | null>(null);
  const [latestEvent, setLatestEvent] = useState<StreamEvent | null>(null);

  // A rejected candidate never reaches financial_node or contract_node, so
  // those steps are removed from the flow rather than shown and skipped.
  const steps: StepId[] = useMemo(
    () =>
      draft.selection_status === "REJECTED"
        ? ["identity", "decision", "review"]
        : ["identity", "decision", "engagement", "compensation", "review"],
    [draft.selection_status],
  );

  const stepId = steps[Math.min(index, steps.length - 1)];
  const meta = STEP_META[stepId];

  const set = useCallback(
    <K extends keyof Draft>(k: K, v: Draft[K]) => {
      setDraft((d) => ({ ...d, [k]: v }));
      // Clear the error as soon as the user edits the field — leaving a stale
      // error under a corrected input is its own usability bug.
      setErrors((e) => (e[k] ? { ...e, [k]: undefined } : e));
    },
    [],
  );

  const handleStateChange = useCallback(
    (s: OnboardingStateResponse | null, ev: StreamEvent | null) => {
      setBackendState(s);
      setLatestEvent(ev);
    },
    [],
  );


  const caption = threadId
    ? MOOD_CAPTION[
        moodFromBackend(
          backendState?.node_status,
          backendState?.current_node,
          latestEvent?.pending_nodes,
        )
      ]
    : MOOD_CAPTION[stepId === "decision" ? "deciding" : meta.mood];

  // ── Navigation ─────────────────────────────────────────────────────────
  const goNext = async () => {
    const found = validateStep(stepId, draft);
    if (Object.values(found).some(Boolean)) {
      setErrors(found);
      // Move focus to the first invalid control so keyboard and screen-reader
      // users land on the problem instead of hunting for it.
      requestAnimationFrame(() => {
        document
          .querySelector<HTMLElement>('[aria-invalid="true"], [role="radiogroup"]')
          ?.focus?.();
      });
      return;
    }
    setErrors({});

    if (stepId !== "review") {
      setDirection(1);
      setIndex((i) => i + 1);
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await api.trigger(toTriggerRequest(draft));
      setThreadId(res.thread_id);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Unknown error.");
    } finally {
      setSubmitting(false);
    }
  };

  const goBack = () => {
    setDirection(-1);
    setErrors({});
    setIndex((i) => Math.max(0, i - 1));
  };

  const restart = () => {
    setDraft(emptyDraft());
    setErrors({});
    setIndex(0);
    setDirection(1);
    setThreadId(null);
    setBackendState(null);
    setLatestEvent(null);
    setSubmitError(null);
  };

  const variants = stepVariants(reduced);

  return (
    <>
      {/* No WebGL here any more. The agent was competing for attention with
          a nine-field form, and the vignette and scrim that existed to keep
          text legible over it are pure cost on a white ground. The scene
          survives on the login screen, where there is nothing to read past
          it. */}
      <main className="page-wash relative min-h-dvh">

        <div className="mx-auto flex min-h-dvh w-full max-w-[1180px] flex-col px-5 py-6 sm:px-8 sm:py-8">
          {/* ── Masthead ─────────────────────────────────────────────── */}
          <header className="flex items-center justify-between gap-4">
            {/* Always a live link. The "go back" CTA below locks during a run
                by design, so this stays available as the standard escape —
                a locked primary path must never become a dead end. */}
            <Link
              href="/"
              className="group flex min-h-[44px] items-center rounded-lg pr-2"
            >
              <Logo
                subtitle={
                  <span className="flex items-center gap-1 whitespace-nowrap text-micro text-fg-muted">
                    <IconArrowLeft className="h-3 w-3 transition-transform duration-[--t-hover] group-hover:-translate-x-0.5" />
                    Dashboard
                  </span>
                }
              />
            </Link>
            <BackendStatus />
          </header>

          {/* ── Stage ────────────────────────────────────────────────── */}
          <div className="flex flex-1 items-center py-8 lg:py-10">
            <div className="grid w-full items-center gap-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-14">
              {/* Left: what this step is for. Sticky, so it stays beside a
                  long form rather than scrolling away. The scrim that used to
                  sit under this copy is gone with the canvas it defended
                  against. */}
              <div className="relative hidden lg:block lg:sticky lg:top-8 lg:self-start lg:pb-4">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={threadId ? `run-${caption}` : stepId}
                    initial={reduced ? { opacity: 0 } : { opacity: 0, y: 16, filter: "blur(8px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    exit={reduced ? { opacity: 0 } : { opacity: 0, y: -12, filter: "blur(6px)" }}
                    transition={T.panel}
                    // `relative` is load-bearing: the scrim above is absolutely
                    // positioned and would otherwise paint over this text.
                    className="relative space-y-5"
                  >
                    <p className="inline-flex items-center gap-2 rounded-full border border-line bg-fill px-3 py-1.5 text-micro font-medium text-fg-muted backdrop-blur-sm">
                      <span
                        className="h-1.5 w-1.5 rounded-full bg-signal animate-breathe"
                        aria-hidden="true"
                      />
                      {caption}
                    </p>
                    <h1 className="text-balance text-[38px] font-semibold leading-[1.08] tracking-[-0.025em] text-fg">
                      {threadId ? "The agent has the floor." : meta.title}
                    </h1>
                    <p className="max-w-[36ch] text-pretty text-[15px] leading-relaxed text-fg-muted">
                      {threadId
                        ? "Every step below is read live from the graph checkpoint. Nothing is sent without your approval."
                        : meta.blurb}
                    </p>
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* Right: the working surface. */}
              <GlassPanel
                layout={reduced ? false : true}
                transition={T.panel}
                className="relative overflow-hidden p-6 shadow-lift sm:p-8"
              >
                {!threadId ? (
                  <div className="space-y-7">
                    <StepProgress
                      steps={steps.map((s) => ({ id: s, label: STEP_META[s].label }))}
                      activeIndex={index}
                      onJump={(i) => { setDirection(-1); setIndex(i); }}
                    />

                    {/* Mobile-only heading: the left column is hidden below lg,
                        so the step still needs a visible title there. */}
                    <div className="lg:hidden">
                      <h1 className="text-balance text-2xl font-semibold leading-tight tracking-[-0.02em] text-fg">
                        {meta.title}
                      </h1>
                      <p className="mt-1.5 text-[13px] leading-relaxed text-fg-muted">
                        {meta.blurb}
                      </p>
                    </div>

                    <AnimatePresence mode="wait" custom={direction} initial={false}>
                      <motion.div
                        key={stepId}
                        custom={direction}
                        variants={variants}
                        initial="enter"
                        animate="center"
                        exit="exit"
                      >
                        <motion.div
                          variants={fieldStagger(reduced)}
                          initial="enter"
                          animate="center"
                        >
                          {stepId === "identity" && (
                            <IdentityStep draft={draft} errors={errors} set={set} />
                          )}
                          {stepId === "decision" && (
                            <DecisionStep draft={draft} errors={errors} set={set} />
                          )}
                          {stepId === "engagement" && (
                            <EngagementStep draft={draft} errors={errors} set={set} />
                          )}
                          {stepId === "compensation" && (
                            <CompensationStep draft={draft} errors={errors} set={set} />
                          )}
                          {stepId === "review" && (
                            <ReviewStep draft={draft} submitError={submitError} />
                          )}
                        </motion.div>
                      </motion.div>
                    </AnimatePresence>

                    <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-6">
                      <Button
                        variant="ghost"
                        onClick={goBack}
                        disabled={index === 0}
                        className="!px-4"
                      >
                        <IconArrowLeft className="h-4 w-4" />
                        Back
                      </Button>

                      <div className="flex items-center gap-3">
                        <span className="hidden text-[11px] tabular-nums text-fg-faint sm:block">
                          {index + 1} / {steps.length}
                        </span>
                        <Button onClick={goNext} loading={submitting}>
                          {stepId === "review" ? "Release to agent" : "Continue"}
                          {!submitting && <IconArrowRight className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <LiveRun
                    threadId={threadId}
                    candidateName={draft.candidate_name}
                    onStateChange={handleStateChange}
                    onRestart={restart}
                  />
                )}
              </GlassPanel>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
