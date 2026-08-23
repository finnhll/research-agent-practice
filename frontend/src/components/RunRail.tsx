import { useEffect, useState } from "react";
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

/** Running, or parked at a gate: idle but still open and resumable. */
function isStoppable(run: Run): boolean {
  return run.status === "running" || run.status === "awaiting_input";
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
  // Delete lives behind a right-click rather than a button on the card. It is
  // irreversible with no undo, and a context menu is close to impossible to
  // open by accident, which a visible x sitting next to every title is not.
  const [menu, setMenu] = useState<{ run: Run; x: number; y: number } | null>(null);
  const queryClient = useQueryClient();

  const refresh = (runId: string) => {
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
  };

  const remove = useMutation({
    mutationFn: (runId: string) => api.deleteRun(runId),
    onSuccess: (_data, runId) => {
      setMenu(null);
      onDeleted(runId);
      refresh(runId);
    },
  });

  const stop = useMutation({
    mutationFn: (runId: string) => api.cancelRun(runId),
    onSuccess: (_data, runId) => {
      setMenu(null);
      refresh(runId);
    },
  });

  const startAgain = useMutation({
    mutationFn: (runId: string) => api.restartRun(runId),
    onSuccess: (fresh) => {
      setMenu(null);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      // Restart produces a new run, so move the user to the one now working.
      onSelect(fresh.run_id);
    },
  });

  const busy = remove.isPending || stop.isPending || startAgain.isPending;
  const menuError = (remove.error ?? stop.error ?? startAgain.error) as Error | null;

  // Anything that moves the menu away from what it points at closes it.
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);
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
              <div key={run.run_id} className="run-wrap">
                <button
                  className={`run ${run.run_id === selectedId ? "on" : ""}`}
                  data-s={statusTone(run.status)}
                  aria-current={run.run_id === selectedId}
                  onClick={() => onSelect(run.run_id)}
                  onContextMenu={(event) => {
                    event.preventDefault();
                    setMenu({ run, x: event.clientX, y: event.clientY });
                  }}
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

      {menu ? (
        <div
          className="ctx"
          role="menu"
          aria-label={`Actions for ${menu.run.goal}`}
          // Nudged in from the pointer so the menu never opens off-screen at
          // the bottom or right of the window.
          style={{
            left: Math.min(menu.x, window.innerWidth - 232),
            top: Math.min(menu.y, window.innerHeight - 96),
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="ctx-title" title={menu.run.goal}>
            {menu.run.goal}
          </div>

          <button
            type="button"
            role="menuitem"
            className="ctx-item"
            // Only a run that is actually going can be stopped -- including one
            // parked at a gate, which is idle but still open.
            disabled={busy || !isStoppable(menu.run)}
            onClick={() => stop.mutate(menu.run.run_id)}
          >
            {stop.isPending ? "Stopping…" : "Stop"}
          </button>

          <button
            type="button"
            role="menuitem"
            className="ctx-item"
            // Restart creates a fresh run from the same question rather than
            // resuming this one, so it makes no sense while this one is live.
            disabled={busy || isStoppable(menu.run)}
            title="Runs the same question again as a new run"
            onClick={() => startAgain.mutate(menu.run.run_id)}
          >
            {startAgain.isPending ? "Starting…" : "Start again"}
          </button>

          <div className="ctx-sep" />

          <button
            type="button"
            role="menuitem"
            className="ctx-danger"
            disabled={busy || menu.run.status === "running"}
            onClick={() => remove.mutate(menu.run.run_id)}
          >
            {remove.isPending ? "Deleting…" : "Delete run"}
          </button>

          {menu.run.status === "running" ? (
            <div className="ctx-note">Stop it before deleting.</div>
          ) : null}
          {menuError ? <div className="ctx-note ctx-error">{menuError.message}</div> : null}
        </div>
      ) : null}
    </aside>
  );
}
