import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { PendingGate } from "../types";

/**
 * The report-review gate. Sits above the finished draft: the report is readable
 * while parked, so the choice is made with the thing itself in view.
 *
 * "Re-write" is offered before "start over" on purpose -- most dissatisfaction
 * with a report is about framing rather than evidence, and re-writing costs one
 * model call and no new searches.
 */
export default function ReportGate({ runId, gate }: { runId: string; gate: PendingGate }) {
  const [instruction, setInstruction] = useState("");
  const [rewriting, setRewriting] = useState(false);
  const queryClient = useQueryClient();

  const respond = useMutation({
    mutationFn: (body: { decision: "accept" | "rewrite"; instruction?: string }) =>
      api.confirmGate(runId, body),
    onSuccess: () => {
      setRewriting(false);
      setInstruction("");
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  return (
    <section className="gate" aria-label="Review the report">
      <div className="gate-head">
        <span className="gate-badge">Before I finish</span>
        <span className="gate-note">
          {gate.payload.revised
            ? "Re-written from the same findings"
            : "The draft below is ready"}
        </span>
      </div>

      {rewriting ? (
        <>
          <p className="gate-lead">What should change? I'll re-write it from the findings I already have — no new searches.</p>
          <textarea
            className="gate-edit gate-edit-plain"
            value={instruction}
            rows={2}
            autoFocus
            aria-label="What to change about the report"
            placeholder="e.g. Lead with the cost comparison and cut the background section"
            onChange={(event) => setInstruction(event.target.value)}
          />
          <div className="gate-actions">
            <button
              className="gate-go"
              disabled={instruction.trim().length < 3 || respond.isPending}
              onClick={() =>
                respond.mutate({ decision: "rewrite", instruction: instruction.trim() })
              }
            >
              {respond.isPending ? "Re-writing…" : "Re-write it"}
            </button>
            <button className="gate-alt" onClick={() => setRewriting(false)}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="gate-lead">
            Accept it as final, or tell me what to change and I'll re-write it.
          </p>
          <div className="gate-actions">
            <button
              className="gate-go"
              disabled={respond.isPending}
              onClick={() => respond.mutate({ decision: "accept" })}
            >
              {respond.isPending ? "Finishing…" : "Accept report"}
            </button>
            <button className="gate-alt" onClick={() => setRewriting(true)}>
              Change something
            </button>
          </div>
        </>
      )}

      {respond.isError ? <p className="error">{(respond.error as Error).message}</p> : null}
    </section>
  );
}
