export type Provider = "openai" | "deepseek" | "anthropic";

export interface ModelConfigInfo {
  provider: Provider;
  model: string;
  base_url: string | null;
  api_key_masked: string | null;
  key_source: "file" | "env" | null;
}

export interface ProviderPreset {
  id: Provider;
  label: string;
  base_url: string | null;
  models: string[];
}

export type RunMode = "autonomous" | "guided";

export interface PendingGate {
  kind: string;
  payload: {
    original_goal?: string;
    rewritten_goal?: string;
    intent?: string;
    rationale?: string;
    assumptions?: string[];
    suggested_dimensions?: string[];
    dimensions?: string[];
  };
  created_at: string;
}

export type RunStatus =
  | "running"
  | "awaiting_input"
  | "complete"
  | "complete_with_caveats"
  | "failed"
  | "blocked"
  | "cancelled";

export interface Run {
  run_id: string;
  goal: string;
  dimensions: string[];
  phase: string;
  status: RunStatus;
  budget: Record<string, number>;
  usage: {
    llm_calls: number;
    tool_calls: number;
    search_calls: number;
    tokens_used: number;
    retries: number;
    replans: number;
  };
  mode: RunMode;
  pending_gate: PendingGate | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface TaskRecord {
  run_id: string;
  plan_id: string;
  plan_version: number;
  task: {
    task_id: string;
    question: string;
    success_criteria: string[];
    required_tools: string[];
    priority: "low" | "medium" | "high";
    dependencies: string[];
  };
  state: string;
  attempt_count: number;
  produced_context: Record<string, unknown>;
}

export interface WorkerAttempt {
  run_id: string;
  plan_id: string;
  plan_version: number;
  task_id: string;
  attempt_id: string;
  attempt_kind: string;
  state: string;
  started_at: string;
  completed_at: string | null;
  result: {
    task_id: string;
    status: string;
    summary: string;
    findings: unknown[];
    sources: unknown[];
    gaps: string[];
  } | null;
  error: string | null;
}

export interface EventRecord {
  sequence: number;
  event_id: string;
  run_id: string;
  event_type: string;
  timestamp: string;
  task_id: string | null;
  attempt_id: string | null;
  data: Record<string, unknown>;
}

export interface SourceRecord {
  source_id: string;
  title: string;
  url: string;
  publisher: string;
  published_at: string | null;
  retrieved_at: string;
  credibility: string;
  notes: string | null;
}

export interface Report {
  report_id: string;
  run_id: string;
  title: string;
  markdown: string;
  structured: {
    executive_summary: string;
    sections: Array<{ heading: string; markdown: string }>;
    comparison_table_markdown: string | null;
    conclusions: Array<{ conclusion: string; confidence: number; basis: string[] }>;
    limitations: string[];
    sources: SourceRecord[];
  };
  guardrail_verdict: "allow" | "revise" | "block";
  created_at: string;
}
