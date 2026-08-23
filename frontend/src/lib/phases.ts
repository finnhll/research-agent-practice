import type { Run, RunStatus, TaskRecord } from "../types";

/**
 * The backend exposes 15 RunPhase values, but most of them are repair loops
 * (plan_repair, worker_repair, report_repair) that describe how the machine is
 * coping rather than how far along it is. Collapse them into the five stages a
 * person actually tracks, and let repairs show up on the affected task instead.
 */
export const STAGES = [
  { id: "check", label: "Check" },
  { id: "plan", label: "Plan" },
  { id: "research", label: "Research" },
  { id: "review", label: "Review" },
  { id: "write", label: "Write" },
] as const;

export type StageId = (typeof STAGES)[number]["id"];
export type StageState = "done" | "now" | "paused" | "waiting";

const PHASE_TO_STAGE: Record<string, StageId> = {
  intake_guardrail: "check",
  clarifying: "check",
  awaiting_confirmation: "check",
  planning: "plan",
  plan_repair: "plan",
  scheduling: "plan",
  executing: "research",
  worker_repair: "research",
  reviewing: "review",
  revising: "review",
  replanning: "review",
  synthesizing: "write",
  awaiting_report_review: "write",
  report_repair: "write",
  final_guardrail: "write",
  finalizing: "write",
};

/** Phases that mean "a previous step is being redone", worth saying out loud. */
const REPAIR_PHASES = new Set([
  "plan_repair",
  "worker_repair",
  "revising",
  "replanning",
  "report_repair",
]);

export function isRepairPhase(phase: string): boolean {
  return REPAIR_PHASES.has(phase);
}

const TERMINAL_STATUSES: RunStatus[] = [
  "complete",
  "complete_with_caveats",
  "failed",
  "blocked",
  "cancelled",
];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/**
 * How far a stopped run actually got. Once a run ends, phase collapses to
 * "terminal", which says nothing about the work already done — so for a run that
 * ended early (cancelled, failed, blocked) we read progress off the tasks it
 * produced rather than showing every stage as untouched.
 */
function reachedIndexFromEvidence(tasks: TaskRecord[]): number {
  if (tasks.length === 0) return 0; // got no further than the intake check
  const allDone = tasks.every((task) => task.state === "completed");
  if (allDone) return 3; // research finished, review never ran
  return 2; // research started but did not finish
}

/**
 * Resolve every stage to done / now / waiting. A finished run marks everything
 * done; a run that stopped early shows the stages it completed as done and the
 * rest as waiting, with nothing marked in-progress.
 */
export function stageStates(run: Run, tasks: TaskRecord[] = []): Record<StageId, StageState> {
  const finished = run.status === "complete" || run.status === "complete_with_caveats";
  const current = PHASE_TO_STAGE[run.phase];
  let currentIndex = current ? STAGES.findIndex((stage) => stage.id === current) : -1;

  // A terminal phase carries no position, so fall back to what the run produced.
  const stopped = isTerminal(run.status) && !finished;
  if (stopped && currentIndex < 0) currentIndex = reachedIndexFromEvidence(tasks);

  const states = {} as Record<StageId, StageState>;
  STAGES.forEach((stage, index) => {
    if (finished) {
      states[stage.id] = "done";
    } else if (currentIndex < 0) {
      states[stage.id] = "waiting";
    } else if (index < currentIndex) {
      states[stage.id] = "done";
    } else if (index === currentIndex) {
      // Parked at a gate the run is not working, so the stage must not animate
      // as though it were.
      if (run.status === "awaiting_input") states[stage.id] = "paused";
      else states[stage.id] = stopped ? "waiting" : "now";
    } else {
      states[stage.id] = "waiting";
    }
  });
  return states;
}

export const STATUS_LABELS: Record<RunStatus, string> = {
  running: "Working",
  awaiting_input: "Needs your OK",
  complete: "Complete",
  complete_with_caveats: "Complete, with caveats",
  failed: "Failed",
  blocked: "Blocked",
  cancelled: "Cancelled",
};

/** Sidebar stripe colour + report badge tone. */
export function statusTone(status: RunStatus): string {
  if (status === "running") return "running";
  if (status === "awaiting_input") return "awaiting";
  if (status === "complete") return "complete";
  if (status === "complete_with_caveats") return "caveats";
  if (status === "blocked" || status === "failed") return "blocked";
  return "idle";
}

export function timeAgo(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
