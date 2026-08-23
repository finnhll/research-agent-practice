import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { PendingGate } from "../types";

/**
 * The question-confirmation gate. It is deliberately the loudest thing on the
 * page: the run is stopped and nothing else will happen until it is answered.
 */
export default function ConfirmGate({
  runId,
  gate,
}: {
  runId: string;
  gate: PendingGate;
}) {
  const payload = gate.payload;
  const proposed = payload.rewritten_goal ?? "";
  const original = payload.original_goal ?? "";
  const changed = proposed.trim() !== original.trim();

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(proposed);
  const queryClient = useQueryClient();

  const confirm = useMutation({
    mutationFn: (goal?: string) => api.confirmGate(runId, goal ? { goal } : {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  return (
    <section className="gate" aria-label="Confirm the research question">
      <div className="gate-head">
        <span className="gate-badge">Before I start</span>
        <span className="gate-note">Nothing has been researched yet</span>
      </div>

      <p className="gate-lead">Here's the question I'm about to research:</p>

      {editing ? (
        <textarea
          className="gate-edit"
          value={draft}
          rows={3}
          aria-label="Edit the research question"
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : (
        <blockquote className="gate-goal">{proposed}</blockquote>
      )}

      {changed && !editing && original ? (
        <details className="gate-diff">
          <summary>You asked</summary>
          <blockquote>{original}</blockquote>
        </details>
      ) : null}

      {payload.rationale ? <p className="gate-why">{payload.rationale}</p> : null}

      {payload.assumptions?.length ? (
        <div className="gate-assumptions">
          <span className="gate-label">I assumed</span>
          <ul>
            {payload.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="gate-actions">
        {editing ? (
          <>
            <button
              className="gate-go"
              disabled={draft.trim().length < 3 || confirm.isPending}
              onClick={() => confirm.mutate(draft.trim())}
            >
              {confirm.isPending ? "Starting…" : "Research this"}
            </button>
            <button
              className="gate-alt"
              onClick={() => {
                setDraft(proposed);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              className="gate-go"
              disabled={confirm.isPending}
              onClick={() => confirm.mutate(undefined)}
            >
              {confirm.isPending ? "Starting…" : "Looks right — go"}
            </button>
            <button className="gate-alt" onClick={() => setEditing(true)}>
              Edit the question
            </button>
          </>
        )}
      </div>

      {confirm.isError ? (
        <p className="error">{(confirm.error as Error).message}</p>
      ) : null}
    </section>
  );
}
