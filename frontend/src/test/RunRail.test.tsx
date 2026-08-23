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

  it("offers no delete affordance until the card is right-clicked", () => {
    renderRail([run()]);
    expect(screen.queryByRole("menuitem", { name: /delete run/i })).not.toBeInTheDocument();
  });

  it("opens a menu naming the run on right-click, without deleting", async () => {
    const user = userEvent.setup();
    renderRail([run()]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });

    expect(screen.getByRole("menuitem", { name: /delete run/i })).toBeInTheDocument();
    // The menu names the run so there is no doubt which one is about to go.
    expect(screen.getByRole("menu", { name: /compare battery chemistries/i })).toBeInTheDocument();
    expect(mocks.deleteRun).not.toHaveBeenCalled();
  });

  it("deletes only when the menu item is chosen", async () => {
    const user = userEvent.setup();
    const onDeleted = renderRail([run()]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });
    await user.click(screen.getByRole("menuitem", { name: /delete run/i }));

    expect(mocks.deleteRun).toHaveBeenCalledWith("run_001");
    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledWith("run_001"));
  });

  it("closes on Escape without deleting", async () => {
    const user = userEvent.setup();
    renderRail([run()]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menuitem", { name: /delete run/i })).not.toBeInTheDocument();
    expect(mocks.deleteRun).not.toHaveBeenCalled();
  });

  it("refuses to offer delete while a run is still going", async () => {
    const user = userEvent.setup();
    renderRail([run({ status: "running" })]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });

    expect(screen.queryByRole("menuitem", { name: /delete run/i })).not.toBeInTheDocument();
    expect(screen.getByText(/stop it before deleting/i)).toBeInTheDocument();
  });
});
