import type { Run, TaskRecord, WorkerAttempt } from "../types";
import { STAGES, isRepairPhase, stageStates } from "../lib/phases";

/** verify -> gather -> produce. See the stage hue rules in styles.css. */
const STAGE_HUE: Record<string, string> = {
  check: "verify",
  plan: "verify",
  research: "work",
  review: "work",
  write: "make",
};

function stageSubtitle(
  stageId: string,
  run: Run,
  tasks: TaskRecord[],
  state: string,
): string {
  if (state === "waiting") return "Waiting";
  if (state === "paused") return "Waiting for you";
  const done = tasks.filter((task) => task.state === "completed").length;
  switch (stageId) {
    case "check":
      return state === "done" ? "Question accepted" : "Checking the question";
    case "plan":
      if (run.phase === "plan_repair") return "Refining the plan";
      return tasks.length ? `${tasks.length} tasks` : "Breaking it down";
    case "research":
      return tasks.length ? `${done} of ${tasks.length} done` : "Starting research";
    case "review":
      return state === "done" ? "Findings reviewed" : "Checking the findings";
    case "write":
      if (run.phase === "final_guardrail") return "Final safety check";
      return state === "done" ? "Report written" : "Writing the report";
    default:
      return "";
  }
}

/** What a worker row should say it is doing, in the user's words not the schema's. */
function taskState(record: TaskRecord): "done" | "run" | "retry" | "wait" {
  if (record.state === "completed") return "done";
  if (record.attempt_count > 1) return "retry";
  if (record.state === "running" || record.state === "in_progress") return "run";
  return "wait";
}

export default function ProgressSpine({
  run,
  tasks,
  attempts,
}: {
  run: Run;
  tasks: TaskRecord[];
  attempts: WorkerAttempt[];
}) {
  const states = stageStates(run, tasks);
  const elapsedMs =
    new Date(run.completed_at ?? run.updated_at).getTime() -
    new Date(run.created_at).getTime();
  const elapsed =
    elapsedMs > 0
      ? `${Math.floor(elapsedMs / 60000)}m ${Math.floor((elapsedMs % 60000) / 1000)}s elapsed`
      : "just started";

  const latestByTask = new Map<string, WorkerAttempt>();
  for (const attempt of attempts) latestByTask.set(attempt.task_id, attempt);

  return (
    <div className="progress">
      <ol className="spine">
        {STAGES.map((stage) => {
          const state = states[stage.id];
          return (
            <li className="stage" data-st={state} data-h={STAGE_HUE[stage.id]} key={stage.id}>
              <div className="stage-top">
                <span className="tick" aria-hidden="true" />
                <span className="stage-name">{stage.label}</span>
              </div>
              <div className="stage-sub">
                {stageSubtitle(stage.id, run, tasks, state)}
              </div>
            </li>
          );
        })}
      </ol>

      {tasks.length ? (
        <div className="workers">
          {tasks.map((record) => {
            const state = taskState(record);
            const latest = latestByTask.get(record.task.task_id);
            const findings = latest?.result?.findings.length ?? 0;
            const sources = latest?.result?.sources.length ?? 0;
            return (
              <div className="wrow" data-s={state} key={record.task.task_id}>
                <span className="wdot" aria-hidden="true" />
                <span className="wq">
                  {record.task.question}
                  {state === "retry" ? (
                    <em>
                      First attempt fell short — retrying (attempt {record.attempt_count})
                    </em>
                  ) : null}
                </span>
                <span className="wstat">
                  {state === "done"
                    ? `${findings} findings · ${sources} sources`
                    : state === "retry"
                      ? `attempt ${record.attempt_count}`
                      : state === "run"
                        ? "searching…"
                        : "queued"}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}

      <div className="prog-foot">
        <span className="mono">{elapsed}</span>
        <span className="spacer" />
        <span className="mono">
          {run.usage.llm_calls} model calls · {run.usage.tool_calls} tool calls
          {run.usage.retries ? ` · ${run.usage.retries} retries` : ""}
        </span>
      </div>

      {isRepairPhase(run.phase) ? (
        <p className="repair-note">
          Redoing an earlier step to close a gap in the evidence.
        </p>
      ) : null}
    </div>
  );
}
