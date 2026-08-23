import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ConfirmGate from "../components/ConfirmGate";
import type { PendingGate } from "../types";

const mocks = vi.hoisted(() => ({ confirmGate: vi.fn() }));

vi.mock("../api", () => ({
  api: mocks,
  reportMarkdownUrl: vi.fn(),
  reportHtmlUrl: vi.fn(),
  API_BASE: "http://localhost:8000",
}));

function gate(overrides: Partial<PendingGate["payload"]> = {}): PendingGate {
  return {
    kind: "confirm_question",
    created_at: "2026-08-21T00:00:00Z",
    payload: {
      original_goal: "batteries",
      rewritten_goal: "Compare LFP, NMC and sodium-ion cells on cost and safety",
      intent: "comparison",
      rationale: "Named the three chemistries so each task has something concrete to research.",
      assumptions: ["Current-generation cells, not lab prototypes"],
      dimensions: ["cost"],
      ...overrides,
    },
  };
}

function renderGate(pending: PendingGate = gate()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConfirmGate runId="run_001" gate={pending} />
    </QueryClientProvider>,
  );
}

describe("ConfirmGate", () => {
  beforeEach(() => {
    mocks.confirmGate.mockReset();
    mocks.confirmGate.mockResolvedValue({});
  });

  it("shows the rewritten question, the reason, and what was assumed", () => {
    renderGate();

    expect(
      screen.getByText("Compare LFP, NMC and sodium-ion cells on cost and safety"),
    ).toBeInTheDocument();
    expect(screen.getByText(/named the three chemistries/i)).toBeInTheDocument();
    expect(screen.getByText(/current-generation cells/i)).toBeInTheDocument();
    // The user is told plainly that nothing has been spent yet.
    expect(screen.getByText(/nothing has been researched yet/i)).toBeInTheDocument();
  });

  it("confirms with no edit, sending an empty body", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.click(screen.getByRole("button", { name: /looks right/i }));

    expect(mocks.confirmGate).toHaveBeenCalledWith("run_001", {});
  });

  it("sends the edited question when the user rewrites it", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.click(screen.getByRole("button", { name: /edit the question/i }));
    const box = screen.getByLabelText(/edit the research question/i);
    await user.clear(box);
    await user.type(box, "Compare only sodium-ion cells");
    await user.click(screen.getByRole("button", { name: /research this/i }));

    expect(mocks.confirmGate).toHaveBeenCalledWith("run_001", {
      goal: "Compare only sodium-ion cells",
    });
  });

  it("offers the original question when the rewrite changed it", () => {
    renderGate();
    expect(screen.getByText(/you asked/i)).toBeInTheDocument();
  });

  it("does not offer a diff when the rewrite matched the original", () => {
    renderGate(gate({ original_goal: "Same question", rewritten_goal: "Same question" }));
    expect(screen.queryByText(/you asked/i)).not.toBeInTheDocument();
  });
});
