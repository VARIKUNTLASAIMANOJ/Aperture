import type { NodeStatus, SelectionStatus } from "./types";

/**
 * The single source of truth for what the 3D agent looks like.
 *
 * Every value here is a TARGET. Nothing in the scene assigns these directly —
 * AgentCore lerps toward them each frame, so a step change reads as the object
 * physically transforming rather than cutting to a new appearance.
 */
export type AgentMood =
  | "dormant"
  | "attentive"
  | "deciding"
  | "computing"
  | "drafting"
  | "holding"
  | "settled"
  | "fault";

export interface AgentProfile {
  /** Core surface colour, linear-RGB safe hex. */
  color: string;
  /** Rim/fresnel colour — the halo that reads as light wrapping the object. */
  rim: string;
  /** Vertex displacement amplitude. 0 = smooth sphere, 0.5 = violent. */
  amplitude: number;
  /** Noise field frequency — low is molten, high is crystalline. */
  frequency: number;
  /** Noise evolution speed. */
  churn: number;
  /** Passive Y-axis rotation, rad/s. */
  spin: number;
  /** Breathing scale depth, 0–1. */
  pulse: number;
  /** Overall object scale. */
  scale: number;
  /** Wireframe shell radius multiplier. */
  shell: number;
  /** Particle drift energy. */
  energy: number;
  /** Facets — drives geometry detail swap (crystalline vs molten). */
  faceted: number;
}

export const AGENT_PROFILES: Record<AgentMood, AgentProfile> = {
  // Waiting for input. Slow, cool, almost still.
  dormant: {
    color: "#0e7490", rim: "#22d3ee",
    amplitude: 0.12, frequency: 1.1, churn: 0.18,
    spin: 0.09, pulse: 0.28, scale: 1.0, shell: 1.34, energy: 0.25, faceted: 0,
  },
  // A field is focused — the agent leans in.
  attentive: {
    color: "#0891b2", rim: "#67e8f9",
    amplitude: 0.19, frequency: 1.5, churn: 0.42,
    spin: 0.16, pulse: 0.42, scale: 1.05, shell: 1.28, energy: 0.5, faceted: 0.15,
  },
  // The SELECTED/REJECTED fork. Tense, sharp, holding its breath.
  deciding: {
    color: "#155e75", rim: "#a5f3fc",
    amplitude: 0.3, frequency: 2.6, churn: 0.2,
    spin: 0.05, pulse: 0.16, scale: 1.02, shell: 1.5, energy: 0.35, faceted: 0.85,
  },
  // Deterministic maths running. Rigid, fast, mechanical.
  computing: {
    color: "#0891b2", rim: "#22d3ee",
    amplitude: 0.16, frequency: 3.4, churn: 1.5,
    spin: 0.52, pulse: 0.3, scale: 1.03, shell: 1.2, energy: 0.95, faceted: 1,
  },
  // LLM drafting prose. Fluid, organic, molten.
  drafting: {
    color: "#0e7490", rim: "#5eead4",
    amplitude: 0.38, frequency: 1.25, churn: 0.95,
    spin: 0.3, pulse: 0.55, scale: 1.07, shell: 1.42, energy: 0.8, faceted: 0,
  },
  // Parked at the HITL gate. Amber, patient, unmistakably waiting.
  holding: {
    color: "#b45309", rim: "#fbbf24",
    amplitude: 0.14, frequency: 1.7, churn: 0.3,
    spin: 0.12, pulse: 0.78, scale: 1.04, shell: 1.6, energy: 0.4, faceted: 0.3,
  },
  // Terminal success. Settles, cools to green, goes quiet.
  settled: {
    color: "#047857", rim: "#34d399",
    amplitude: 0.07, frequency: 1.0, churn: 0.12,
    spin: 0.07, pulse: 0.2, scale: 0.97, shell: 1.24, energy: 0.18, faceted: 0,
  },
  // Something broke. Jittery, red, high frequency.
  fault: {
    color: "#b91c1c", rim: "#fca5a5",
    amplitude: 0.34, frequency: 4.5, churn: 2.4,
    spin: 0.04, pulse: 0.9, scale: 0.99, shell: 1.46, energy: 1, faceted: 0.6,
  },
};

/** Copy shown beside the agent per mood. */
export const MOOD_CAPTION: Record<AgentMood, string> = {
  dormant: "Standing by",
  attentive: "Listening",
  deciding: "Awaiting your decision",
  computing: "Running deterministic payroll maths",
  drafting: "Drafting the agreement",
  holding: "Paused for human approval",
  settled: "Workflow complete",
  fault: "Workflow halted",
};

/**
 * Maps live backend graph state onto a mood.
 * Mirrors the node names in core/graph.py.
 */
export function moodFromBackend(
  nodeStatus: NodeStatus | null | undefined,
  currentNode: string | null | undefined,
  pendingNodes: string[] | undefined,
): AgentMood {
  if (nodeStatus === "ERROR" || currentNode === "error_handler") return "fault";
  if (nodeStatus === "WAITING_HITL") return "holding";

  // Parked at interrupt_before=["email_node"] — the approval gate.
  if (pendingNodes?.includes("email_node")) return "holding";

  switch (currentNode) {
    case "financial_node":
      return "computing";
    case "contract_node":
      return "drafting";
    case "triage_node":
      return "deciding";
    case "email_node":
      return nodeStatus === "COMPLETE" ? "settled" : "holding";
    default:
      break;
  }
  if (nodeStatus === "COMPLETE") return "settled";
  return "computing";
}

/** Tints the decision step by which branch the operator picked. */
export function decisionTint(selection: SelectionStatus | null): AgentProfile {
  const base = AGENT_PROFILES.deciding;
  if (selection === "SELECTED") {
    return { ...base, color: "#0f766e", rim: "#5eead4", pulse: 0.4, spin: 0.22 };
  }
  if (selection === "REJECTED") {
    return { ...base, color: "#334155", rim: "#94a3b8", pulse: 0.1, spin: 0.02, amplitude: 0.1 };
  }
  return base;
}
