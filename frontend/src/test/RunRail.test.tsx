import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RunRail from "../components/RunRail";
import type { Run } from "../types";

const mocks = vi.hoisted(() => ({
  deleteRun: vi.fn(),
  cancelRun: vi.fn(),
  restartRun: vi.fn(),
}));

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

function renderRail(runs: Run[], onDeleted = vi.fn(), onSelect = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RunRail
        runs={runs}
        selectedId="run_001"
        onSelect={onSelect}
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
    mocks.cancelRun.mockReset();
    mocks.cancelRun.mockResolvedValue({});
    mocks.restartRun.mockReset();
    mocks.restartRun.mockResolvedValue({ run_id: "run_002" });
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

  it("offers Stop but not Start or Delete while a run is going", async () => {
    const user = userEvent.setup();
    renderRail([run({ status: "running" })]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });

    expect(screen.getByRole("menuitem", { name: /^stop$/i })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: /start again/i })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /delete run/i })).toBeDisabled();
    expect(screen.getByText(/stop it before deleting/i)).toBeInTheDocument();
  });

  it("offers Start again and Delete but not Stop once a run is finished", async () => {
    const user = userEvent.setup();
    renderRail([run({ status: "complete" })]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });

    expect(screen.getByRole("menuitem", { name: /^stop$/i })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /start again/i })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: /delete run/i })).toBeEnabled();
  });

  it("treats a run parked at a gate as stoppable", async () => {
    const user = userEvent.setup();
    renderRail([run({ status: "awaiting_input" })]);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });
    await user.click(screen.getByRole("menuitem", { name: /^stop$/i }));

    expect(mocks.cancelRun).toHaveBeenCalledWith("run_001");
  });

  it("moves to the new run when Start again is chosen", async () => {
    const user = userEvent.setup();
    mocks.restartRun.mockResolvedValue({ run_id: "run_002" });
    const onSelect = vi.fn();
    renderRail([run({ status: "complete" })], vi.fn(), onSelect);

    await user.pointer({
      keys: "[MouseRight]",
      target: screen.getByText("Compare battery chemistries"),
    });
    await user.click(screen.getByRole("menuitem", { name: /start again/i }));

    expect(mocks.restartRun).toHaveBeenCalledWith("run_001");
    // Restart makes a different run, so the workspace has to follow it.
    await vi.waitFor(() => expect(onSelect).toHaveBeenCalledWith("run_002"));
  });
});
