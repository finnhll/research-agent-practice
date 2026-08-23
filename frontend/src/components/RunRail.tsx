import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { Run } from "../types";
import { statusTone, timeAgo } from "../lib/phases";

function groupLabel(iso: string): string {
  const created = new Date(iso);
  const today = new Date();
  const sameDay =
    created.getFullYear() === today.getFullYear() &&
    created.getMonth() === today.getMonth() &&
    created.getDate() === today.getDate();
  return sameDay ? "Today" : "Earlier";
}

function summarise(run: Run): string {
  if (run.status === "running") return "Working";
  if (run.status === "awaiting_input") return "Needs your OK";
  if (run.status === "complete") return "Complete";
  if (run.status === "complete_with_caveats") return "Complete, with caveats";
  if (run.status === "blocked") return "Blocked";
  if (run.status === "failed") return "Failed";
  return "Cancelled";
}

export default function RunRail({
  runs,
  selectedId,
  onSelect,
  onNew,
  onOpenSettings,
  onDeleted,
  loading,
}: {
  runs: Run[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
  onNew: () => void;
  onOpenSettings: () => void;
  onDeleted: (runId: string) => void;
  loading: boolean;
}) {
  // Deleting is irreversible and there is no undo, so the x only arms the
  // action -- a second, differently-labelled click actually destroys it.
  const [armed, setArmed] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const remove = useMutation({
    mutationFn: (runId: string) => api.deleteRun(runId),
    onSuccess: (_data, runId) => {
      setArmed(null);
      onDeleted(runId);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const groups: Array<[string, Run[]]> = [];
  for (const run of runs) {
    const label = groupLabel(run.created_at);
    const last = groups[groups.length - 1];
    if (last && last[0] === label) last[1].push(run);
    else groups.push([label, [run]]);
  }

  return (
    <aside className="rail">
      <div className="rail-head">
        <div className="wordmark">
          <span className="mark" aria-hidden="true">
            <span />
          </span>
          <span>
            <b>Research Desk</b>
            <small>Orchestrator + workers</small>
          </span>
        </div>
        <button className="btn-new" onClick={onNew}>
          + New question
        </button>
      </div>

      <nav className="queue" aria-label="Your research runs">
        {loading ? <p className="queue-empty">Loading…</p> : null}
        {!loading && runs.length === 0 ? (
          <p className="queue-empty">No runs yet. Ask your first question.</p>
        ) : null}
        {groups.map(([label, groupRuns]) => (
          <div key={label}>
            <div className="queue-label">{label}</div>
            {groupRuns.map((run) => (
              <div
                key={run.run_id}
                className={`run-wrap ${armed === run.run_id ? "armed" : ""}`}
              >
                <button
                  className={`run ${run.run_id === selectedId ? "on" : ""}`}
                  data-s={statusTone(run.status)}
                  aria-current={run.run_id === selectedId}
                  onClick={() => onSelect(run.run_id)}
                >
                  <span className="run-goal">{run.goal}</span>
                  <span className="run-meta">
                    {run.status === "running" || run.status === "awaiting_input" ? (
                      <span className="pulse" />
                    ) : null}
                    {summarise(run)}
                    <span className="dot" />
                    {timeAgo(run.created_at)}
                  </span>
                </button>

                {armed === run.run_id ? (
                  <span className="run-confirm">
                    <button
                      className="run-confirm-yes"
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(run.run_id)}
                    >
                      {remove.isPending ? "Deleting…" : "Delete"}
                    </button>
                    <button className="run-confirm-no" onClick={() => setArmed(null)}>
                      Keep
                    </button>
                  </span>
                ) : run.status === "running" ? null : (
                  <button
                    className="run-x"
                    aria-label={`Delete run: ${run.goal}`}
                    title="Delete this run"
                    onClick={() => setArmed(run.run_id)}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
      </nav>

      <div className="rail-foot">
        <button className="model-chip" onClick={onOpenSettings}>
          <span className="live" aria-hidden="true" />
          <span className="name">Model API</span>
          <span className="gear" aria-hidden="true">
            ⚙
          </span>
        </button>
      </div>
    </aside>
  );
}
