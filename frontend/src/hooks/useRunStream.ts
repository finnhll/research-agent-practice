import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "../api";

const eventTypes = [
  "run.phase.changed",
  "intake_guardrail.completed",
  "plan.validated",
  "worker.attempt.started",
  "worker.attempt.completed",
  "review.completed",
  "synthesis.completed",
  "final_guardrail.completed",
  "run.completed",
  "run.terminated",
  "run.cancelled",
];

export function useRunStream(runId: string, active: boolean) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!active) return;
    const source = new EventSource(`${API_BASE}/api/runs/${runId}/stream`);
    const invalidate = () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-data", runId] });
    };

    source.onopen = invalidate;
    for (const eventType of eventTypes) {
      source.addEventListener(eventType, invalidate);
    }

    return () => source.close();
  }, [active, queryClient, runId]);
}
