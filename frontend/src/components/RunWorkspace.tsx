import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, reportHtmlUrl, reportMarkdownUrl } from "../api";
import { useRunStream } from "../hooks/useRunStream";
import type { Run } from "../types";
import { STATUS_LABELS, isTerminal, statusTone } from "../lib/phases";
import ConfirmGate from "./ConfirmGate";
import Inspector from "./Inspector";
import ReportGate from "./ReportGate";
import ProgressSpine from "./ProgressSpine";
import ReportViewer from "./ReportViewer";

export default function RunWorkspace({
  run: initialRun,
  traceOpen,
  onToggleTrace,
  onToggleRail,
  onRestarted,
}: {
  run: Run;
  traceOpen: boolean;
  onToggleTrace: () => void;
  onToggleRail: () => void;
  onRestarted: (run: Run) => void;
}) {
  const queryClient = useQueryClient();
  const runId = initialRun.run_id;

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    initialData: initialRun,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // Keep polling while parked at a gate too: confirming it elsewhere (or
      // in another tab) should show up here without a manual reload.
      return status === "running" || status === "awaiting_input" ? 1500 : false;
    },
  });
  const run = runQuery.data ?? initialRun;
  const waiting = run.status === "awaiting_input";
  const active = run.status === "running";
  useRunStream(runId, active);

  const tasksQuery = useQuery({
    queryKey: ["run-data", runId, "tasks"],
    queryFn: () => api.listTasks(runId),
    refetchInterval: active ? 1500 : false,
  });
  const attemptsQuery = useQuery({
    queryKey: ["run-data", runId, "attempts"],
    queryFn: () => api.listAttempts(runId),
    refetchInterval: active ? 1500 : false,
  });
  const eventsQuery = useQuery({
    queryKey: ["run-data", runId, "events"],
    queryFn: () => api.listEvents(runId),
    enabled: traceOpen,
    refetchInterval: active && traceOpen ? 1500 : false,
  });
  const reportQuery = useQuery({
    queryKey: ["run-data", runId, "report"],
    queryFn: () => api.getReport(runId),
    // Also while parked at the report gate: the whole point is to decide with
    // the draft in front of you.
    enabled: !active || waiting,
    refetchInterval: waiting ? 2000 : false,
    retry: false,
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  const restart = useMutation({
    mutationFn: () => api.restartRun(runId),
    onSuccess: (fresh) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      onRestarted(fresh);
    },
  });

  const tasks = tasksQuery.data ?? [];
  const attempts = attemptsQuery.data ?? [];
  const report = reportQuery.data;
  const blocked = run.status === "blocked" || run.status === "failed";
  // A run that never reached a report is the one worth offering to run again.
  const stoppedEarly =
    run.status === "cancelled" || run.status === "failed" || run.status === "blocked";

  return (
    <>
      <main className="work">
        <div className="topbar">
          <button className="tbtn railtoggle" onClick={onToggleRail} aria-label="Show runs">
            ☰
          </button>
          <h1 title={run.goal}>{run.goal}</h1>
          <span className="spacer" />
          <button className="tbtn" onClick={onToggleTrace} aria-expanded={traceOpen}>
            Trace
          </button>
          {report ? (
            <>
              <a
                className="tbtn bordered"
                href={reportHtmlUrl(runId)}
                target="_blank"
                rel="noreferrer"
              >
                HTML
              </a>
              <a
                className="tbtn bordered"
                href={reportMarkdownUrl(runId)}
                target="_blank"
                rel="noreferrer"
              >
                Markdown
              </a>
            </>
          ) : null}
          {!active && stoppedEarly ? (
            <button
              className="tbtn bordered"
              onClick={() => restart.mutate()}
              disabled={restart.isPending}
            >
              {restart.isPending ? "Starting…" : "Start over"}
            </button>
          ) : null}
          {active ? (
            <button
              className="tbtn stop"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              {cancel.isPending ? "Stopping…" : "Stop"}
            </button>
          ) : null}
        </div>

        <div className="canvas">
          <div className="sheet">
            {run.dimensions.length ? (
              <div className="focus-row">
                <span className="focus-label">Focus</span>
                {run.dimensions.map((dimension) => (
                  <span className="focus-tag" key={dimension}>
                    {dimension}
                  </span>
                ))}
              </div>
            ) : null}

            {waiting && run.pending_gate?.kind === "confirm_question" ? (
              <ConfirmGate runId={runId} gate={run.pending_gate} />
            ) : null}
            {waiting && run.pending_gate?.kind === "confirm_report" ? (
              <ReportGate runId={runId} gate={run.pending_gate} />
            ) : null}

            {blocked ? (
              <div className="blocked">
                <h3>
                  {run.status === "blocked" ? "This one didn't run" : "This run failed"}
                </h3>
                <p>
                  {run.status === "blocked"
                    ? "The intake check stopped this question before any research started, so nothing was searched and no sources were fetched."
                    : "The run stopped before a report could be written."}
                </p>
                {run.error ? (
                  <div className="why">
                    <b>Reason</b>
                    {run.error}
                  </div>
                ) : null}
              </div>
            ) : (
              <ProgressSpine run={run} tasks={tasks} attempts={attempts} />
            )}

            {report ? <ReportViewer report={report} /> : null}

            {active ? (
              <p className="await-note">
                Your report will appear here when the research is done. You can leave this
                page — the run keeps going.
              </p>
            ) : null}

            {!active && !waiting && !report && !blocked ? (
              <p className="await-note">
                <span className={`status-badge ${statusTone(run.status)}`}>
                  {STATUS_LABELS[run.status]}
                </span>
                {isTerminal(run.status) ? " — no report was produced for this run." : null}
              </p>
            ) : null}
          </div>
        </div>
      </main>

      {traceOpen ? (
        <Inspector
          run={run}
          tasks={tasks}
          attempts={attempts}
          events={eventsQuery.data?.events ?? []}
          onClose={onToggleTrace}
        />
      ) : null}
    </>
  );
}
