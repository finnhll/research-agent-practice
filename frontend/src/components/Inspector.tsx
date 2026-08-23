import type { EventRecord, Run, TaskRecord, WorkerAttempt } from "../types";

interface Problem {
  key: string;
  where: string;
  detail: string;
  when: string | null;
}

/** Events whose payload is worth showing even when nothing failed. */
const NOISY_DATA_KEYS = new Set(["error", "status", "reason", "verdict", "detail"]);

function describeData(data: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (value === null || value === undefined || value === "") continue;
    if (!NOISY_DATA_KEYS.has(key)) continue;
    parts.push(`${key}: ${String(value)}`);
  }
  return parts.join(" · ");
}

/**
 * Collect every failure the run recorded, from three places that each know about
 * a different kind of thing going wrong: the run's own terminal error, a worker
 * attempt that errored or came back blocked, and any event carrying an error
 * payload.
 */
function collectProblems(
  run: Run,
  attempts: WorkerAttempt[],
  events: EventRecord[],
): Problem[] {
  const problems: Problem[] = [];

  if (run.error) {
    problems.push({
      key: "run-error",
      where: "Run",
      detail: run.error,
      when: run.completed_at ?? run.updated_at,
    });
  }

  for (const attempt of attempts) {
    const failedResult =
      attempt.result && attempt.result.status !== "completed"
        ? `${attempt.result.status}: ${attempt.result.summary}`
        : null;
    const detail = attempt.error ?? failedResult;
    if (!detail) continue;
    problems.push({
      key: attempt.attempt_id,
      where: attempt.task_id,
      detail,
      when: attempt.completed_at ?? attempt.started_at,
    });
  }

  for (const event of events) {
    const error = event.data?.error;
    if (!error) continue;
    problems.push({
      key: `${event.event_id}-err`,
      where: event.task_id ?? event.event_type,
      detail: String(error),
      when: event.timestamp,
    });
  }

  return problems;
}

function budgetRows(run: Run): Array<{ label: string; used: number; cap: number | null }> {
  return [
    { label: "Model calls", used: run.usage.llm_calls, cap: null },
    { label: "Searches", used: run.usage.search_calls, cap: null },
    {
      label: "Retries",
      used: run.usage.retries,
      cap: run.budget.max_retries_per_task ?? null,
    },
    { label: "Replans", used: run.usage.replans, cap: run.budget.max_replans ?? null },
  ];
}

export default function Inspector({
  run,
  tasks,
  attempts,
  events,
  onClose,
}: {
  run: Run;
  tasks: TaskRecord[];
  attempts: WorkerAttempt[];
  events: EventRecord[];
  onClose: () => void;
}) {
  const attemptsByTask = new Map<string, WorkerAttempt[]>();
  for (const attempt of attempts) {
    const list = attemptsByTask.get(attempt.task_id) ?? [];
    list.push(attempt);
    attemptsByTask.set(attempt.task_id, list);
  }
  const recent = [...events].reverse();
  const problems = collectProblems(run, attempts, events);

  return (
    <aside className="inspector" aria-label="Research trace">
      <div className="insp-head">
        <b>Research trace</b>
        <span className="spacer" />
        <button className="x" onClick={onClose} aria-label="Close trace">
          ✕
        </button>
      </div>
      <div className="insp-body">
        {problems.length ? (
          <section className="insp-sec">
            <h4>Problems ({problems.length})</h4>
            <ul className="problems">
              {problems.map((problem) => (
                <li key={problem.key}>
                  <div className="problem-top">
                    <span className="tid">{problem.where}</span>
                    {problem.when ? (
                      <span className="ts">
                        {new Date(problem.when).toLocaleTimeString()}
                      </span>
                    ) : null}
                  </div>
                  <p>{problem.detail}</p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="insp-sec">
          <h4>Budget used</h4>
          <div className="stat-grid">
            {budgetRows(run).map((row) => (
              <div className="stat" key={row.label}>
                <b>
                  {row.used}
                  {row.cap !== null ? <small>/{row.cap}</small> : null}
                </b>
                <small>{row.label}</small>
              </div>
            ))}
          </div>
        </section>

        <section className="insp-sec">
          <h4>Plan</h4>
          {tasks.length === 0 ? <p className="muted">No tasks planned yet.</p> : null}
          {tasks.map((record) => {
            const taskAttempts = attemptsByTask.get(record.task.task_id) ?? [];
            const latest = taskAttempts[taskAttempts.length - 1];
            return (
              <article className="task-i" key={record.task.task_id}>
                <div className="task-i-top">
                  <span className="tid">{record.task.task_id}</span>
                  <span className={`pill ${record.state}`}>{record.state}</span>
                </div>
                <p>{record.task.question}</p>
                <div className="counts">
                  <span>{latest?.result?.findings.length ?? 0} findings</span>
                  <span>{latest?.result?.sources.length ?? 0} sources</span>
                  <span>
                    {record.attempt_count} attempt{record.attempt_count === 1 ? "" : "s"}
                  </span>
                </div>
                {latest?.result?.summary ? (
                  <p className="task-i-summary">{latest.result.summary}</p>
                ) : null}
              </article>
            );
          })}
        </section>

        <section className="insp-sec">
          <h4>Events</h4>
          {recent.length === 0 ? <p className="muted">No events yet.</p> : null}
          <ol className="log">
            {recent.map((event, index) => {
              const detail = describeData(event.data ?? {});
              const failed = Boolean(event.data?.error);
              return (
                <li
                  key={event.event_id}
                  className={[index === 0 ? "hi" : "", failed ? "bad" : ""]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <span className="ev">{event.event_type}</span>
                  <span className="ts">
                    {new Date(event.timestamp).toLocaleTimeString()}
                    {event.task_id ? ` · ${event.task_id}` : ""}
                  </span>
                  {detail ? <span className="ev-data">{detail}</span> : null}
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </aside>
  );
}
