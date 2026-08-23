import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RunRail from "../components/RunRail";
import type { Run } from "../types";

const mocks = vi.hoisted(() => ({ deleteRun: vi.fn() }));

vi.mock("../api", () => ({
  api: mocks,
  reportMarkdownUrl: vi.fn(),
  reportHtmlUrl: vi.fn(),
  API_BASE: "http://localhost:8000",
}));

function run(overrides: Partial<Run> = {}): Run {
  return {
    run_id: "run_001",
    goal: "Compare battery chemistries",
    dimensions: [],
    phase: "terminal",
    status: "complete",
    budget: {},
    usage: {
      llm_calls: 0,
      tool_calls: 0,
      search_calls: 0,
      tokens_used: 0,
      retries: 0,
      replans: 0,
    },
    mode: "guided",
    pending_gate: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
    error: null,
    ...overrides,
  } as Run;
}

function renderRail(runs: Run[], onDeleted = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RunRail
        runs={runs}
        selectedId="run_001"
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onOpenSettings={vi.fn()}
        onDeleted={onDeleted}
        loading={false}
      />
    </QueryClientProvider>,
  );
  return onDeleted;
}

describe("RunRail delete", () => {
  beforeEach(() => {
    mocks.deleteRun.mockReset();
    mocks.deleteRun.mockResolvedValue(undefined);
  });

  it("does not delete on the first click -- it only arms", async () => {
    const user = userEvent.setup();
    renderRail([run()]);

    await user.click(screen.getByRole("button", { name: /delete run:/i }));

    expect(mocks.deleteRun).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /keep/i })).toBeInTheDocument();
  });

  it("deletes once confirmed, and tells the parent which run went", async () => {
    const user = userEvent.setup();
    const onDeleted = renderRail([run()]);

    await user.click(screen.getByRole("button", { name: /delete run:/i }));
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    expect(mocks.deleteRun).toHaveBeenCalledWith("run_001");
    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledWith("run_001"));
  });

  it("backs out cleanly on Keep", async () => {
    const user = userEvent.setup();
    renderRail([run()]);

    await user.click(screen.getByRole("button", { name: /delete run:/i }));
    await user.click(screen.getByRole("button", { name: /keep/i }));

    expect(mocks.deleteRun).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /delete run:/i })).toBeInTheDocument();
  });

  it("offers no delete while a run is still going", () => {
    renderRail([run({ status: "running" })]);
    expect(screen.queryByRole("button", { name: /delete run:/i })).not.toBeInTheDocument();
  });
});
