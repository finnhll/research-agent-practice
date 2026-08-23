import type {
  EventRecord,
  ModelConfigInfo,
  Provider,
  ProviderPreset,
  Report,
  Run,
  RunMode,
  TaskRecord,
  WorkerAttempt,
} from "./types";

export const API_BASE =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Request failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  createRun(goal: string, dimensions: string[], mode: RunMode = "guided"): Promise<Run> {
    return request<Run>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ goal, dimensions, mode }),
    });
  },
  confirmGate(
    runId: string,
    update: { goal?: string; dimensions?: string[] } = {},
  ): Promise<Run> {
    return request<Run>(`/api/runs/${runId}/confirm`, {
      method: "POST",
      body: JSON.stringify(update),
    });
  },
  listRuns(): Promise<Run[]> {
    return request<Run[]>("/api/runs");
  },
  getRun(runId: string): Promise<Run> {
    return request<Run>(`/api/runs/${runId}`);
  },
  async cancelRun(runId: string): Promise<Run> {
    return request<Run>(`/api/runs/${runId}`, { method: "DELETE" });
  },
  restartRun(runId: string): Promise<Run> {
    return request<Run>(`/api/runs/${runId}/restart`, { method: "POST" });
  },
  listTasks(runId: string): Promise<TaskRecord[]> {
    return request<TaskRecord[]>(`/api/runs/${runId}/tasks`);
  },
  listAttempts(runId: string): Promise<WorkerAttempt[]> {
    return request<WorkerAttempt[]>(`/api/runs/${runId}/attempts`);
  },
  listEvents(runId: string): Promise<{ events: EventRecord[] }> {
    return request<{ events: EventRecord[] }>(`/api/runs/${runId}/events`);
  },
  getReport(runId: string): Promise<Report> {
    return request<Report>(`/api/runs/${runId}/report`);
  },
  getModelProviders(): Promise<ProviderPreset[]> {
    return request<ProviderPreset[]>("/api/model-providers");
  },
  getModelConfig(): Promise<ModelConfigInfo> {
    return request<ModelConfigInfo>("/api/model-config");
  },
  saveModelConfig(update: {
    provider?: Provider;
    model?: string;
    base_url?: string;
    api_key?: string;
  }): Promise<ModelConfigInfo> {
    return request<ModelConfigInfo>("/api/model-config", {
      method: "POST",
      body: JSON.stringify(update),
    });
  },
  testModelConfig(): Promise<{ ok: boolean; error?: string; model_found?: boolean; model?: string }> {
    return request("/api/model-config/test", { method: "POST" });
  },
};

export function reportMarkdownUrl(runId: string): string {
  return `${API_BASE}/api/runs/${runId}/report.md`;
}

export function reportHtmlUrl(runId: string): string {
  return `${API_BASE}/api/runs/${runId}/report.html`;
}
