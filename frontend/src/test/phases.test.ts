import { describe, expect, it } from "vitest";
import { STAGES, stageStates } from "../lib/phases";
import type { Run } from "../types";

function run(phase: string, status: Run["status"] = "running"): Run {
  return {
    run_id: "run_001",
    goal: "g",
    dimensions: [],
    phase,
    status,
    budget: {},
    usage: {
      llm_calls: 0,
      tool_calls: 0,
      search_calls: 0,
      tokens_used: 0,
      retries: 0,
      replans: 0,
    },
    mode: "guided",
    pending_gate: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
    error: null,
  } as Run;
}

/**
 * Every backend RunPhase except the two bookends must map to a stage. A phase
 * missing from the map resolves to no current stage, which silently renders the
 * whole spine as "Waiting" -- that is exactly how awaiting_report_review
 * shipped broken.
 */
const MAPPED_PHASES = [
  "intake_guardrail",
  "clarifying",
  "awaiting_confirmation",
  "planning",
  "plan_repair",
  "scheduling",
  "executing",
  "worker_repair",
  "reviewing",
  "revising",
  "replanning",
  "synthesizing",
  "awaiting_report_review",
  "report_repair",
  "final_guardrail",
  "finalizing",
];

describe("stageStates", () => {
  it.each(MAPPED_PHASES)("resolves a current stage for %s", (phase) => {
    const states = stageStates(run(phase));
    const values = STAGES.map((stage) => states[stage.id]);
    expect(values.some((value) => value === "now" || value === "paused")).toBe(true);
  });

  it("marks earlier stages done and the current one paused at the report gate", () => {
    const states = stageStates(run("awaiting_report_review", "awaiting_input"));
    expect(states.check).toBe("done");
    expect(states.plan).toBe("done");
    expect(states.research).toBe("done");
    expect(states.review).toBe("done");
    expect(states.write).toBe("paused");
  });

  it("pauses rather than animates at the question gate", () => {
    const states = stageStates(run("awaiting_confirmation", "awaiting_input"));
    expect(states.check).toBe("paused");
    expect(states.plan).toBe("waiting");
  });

  it("marks everything done once the run completes", () => {
    const states = stageStates(run("terminal", "complete"));
    expect(STAGES.every((stage) => states[stage.id] === "done")).toBe(true);
  });
});
