import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import App from "../App";

const mocks = vi.hoisted(() => ({
  createRun: vi.fn(),
  listRuns: vi.fn(),
  getRun: vi.fn(),
  listTasks: vi.fn(),
  listAttempts: vi.fn(),
  listEvents: vi.fn(),
  getReport: vi.fn(),
  cancelRun: vi.fn(),
  restartRun: vi.fn(),
}));

vi.mock("../api", () => ({
  api: mocks,
  reportMarkdownUrl: vi.fn(() => "http://localhost:8000/report.md"),
  reportHtmlUrl: vi.fn(() => "http://localhost:8000/report.html"),
  API_BASE: "http://localhost:8000",
}));

function makeRun(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run_001",
    goal: "Compare battery chemistries",
    dimensions: [],
    phase: "planning",
    status: "running",
    budget: {},
    mode: "guided",
    pending_gate: null,
    usage: {
      llm_calls: 0,
      tool_calls: 0,
      search_calls: 0,
      tokens_used: 0,
      retries: 0,
      replans: 0,
    },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
    error: null,
    ...overrides,
  };
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("renders the composer and the empty run rail", async () => {
    mocks.listRuns.mockResolvedValue([]);
    renderApp();

    expect(await screen.findByText(/what do you want researched/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/research goal/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
    expect(await screen.findByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("submits a research goal with no dimensions preselected", async () => {
    mocks.listRuns.mockResolvedValue([]);
    mocks.createRun.mockResolvedValue(makeRun());
    const user = userEvent.setup();
    renderApp();

    await user.type(
      await screen.findByLabelText(/research goal/i),
      "Compare battery chemistries",
    );
    await user.click(screen.getByRole("button", { name: /send/i }));

    await vi.waitFor(() =>
      expect(mocks.createRun).toHaveBeenCalledWith("Compare battery chemistries", [], "guided"),
    );
  });

  it("submits the dimensions the user picked, including a custom focus", async () => {
    mocks.listRuns.mockResolvedValue([]);
    mocks.createRun.mockResolvedValue(makeRun());
    const user = userEvent.setup();
    renderApp();

    await user.type(
      await screen.findByLabelText(/research goal/i),
      "Compare battery chemistries",
    );
    await user.click(screen.getByRole("button", { name: "cost" }));
    await user.click(screen.getByRole("button", { name: /add focus/i }));
    await user.type(screen.getByLabelText(/add a focus area/i), "supply chain{Enter}");
    await user.click(screen.getByRole("button", { name: /send/i }));

    await vi.waitFor(() =>
      expect(mocks.createRun).toHaveBeenCalledWith(
        "Compare battery chemistries",
        ["cost", "supply chain"],
        "guided",
      ),
    );
  });

  it("stops the user selecting more than two dimensions", async () => {
    mocks.listRuns.mockResolvedValue([]);
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: "cost" }));
    await user.click(screen.getByRole("button", { name: "risks" }));

    expect(screen.getByRole("button", { name: "tradeoffs" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /add focus/i })).toBeDisabled();
    expect(screen.getByText(/2 of 2 — deselect to swap/i)).toBeInTheDocument();
  });

  it("lets the user swap a dimension once at the limit", async () => {
    mocks.listRuns.mockResolvedValue([]);
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: "cost" }));
    await user.click(screen.getByRole("button", { name: "risks" }));
    await user.click(screen.getByRole("button", { name: "cost" }));

    expect(screen.getByRole("button", { name: "tradeoffs" })).toBeEnabled();
  });

  it("opens the run workspace as soon as a question is submitted", async () => {
    const fresh = makeRun();
    mocks.listRuns.mockResolvedValue([]);
    mocks.createRun.mockResolvedValue(fresh);
    mocks.getRun.mockResolvedValue(fresh);
    mocks.listTasks.mockResolvedValue([]);
    mocks.listAttempts.mockResolvedValue([]);
    mocks.listEvents.mockResolvedValue({ events: [] });
    mocks.getReport.mockRejectedValue(new Error("not ready"));

    const user = userEvent.setup();
    renderApp();

    await user.type(
      await screen.findByLabelText(/research goal/i),
      "Compare battery chemistries",
    );
    await user.click(screen.getByRole("button", { name: /send/i }));

    // the composer is replaced by the execution view, not left on screen
    expect(await screen.findByRole("button", { name: /trace/i })).toBeInTheDocument();
    expect(screen.queryByText(/what do you want researched/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
  });

  it("returns to the composer only when New question is clicked", async () => {
    const fresh = makeRun();
    mocks.listRuns.mockResolvedValue([fresh]);
    mocks.getRun.mockResolvedValue(fresh);
    mocks.listTasks.mockResolvedValue([]);
    mocks.listAttempts.mockResolvedValue([]);
    mocks.listEvents.mockResolvedValue({ events: [] });
    mocks.getReport.mockRejectedValue(new Error("not ready"));

    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: /compare battery/i }));
    expect(await screen.findByRole("button", { name: /trace/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new question/i }));
    expect(await screen.findByText(/what do you want researched/i)).toBeInTheDocument();
  });
});
