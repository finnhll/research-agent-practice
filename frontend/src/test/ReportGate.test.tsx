import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ReportGate from "../components/ReportGate";
import type { PendingGate } from "../types";

const mocks = vi.hoisted(() => ({ confirmGate: vi.fn() }));

vi.mock("../api", () => ({
  api: mocks,
  reportMarkdownUrl: vi.fn(),
  reportHtmlUrl: vi.fn(),
  API_BASE: "http://localhost:8000",
}));

function gate(revised = false): PendingGate {
  return {
    kind: "confirm_report",
    created_at: "2026-08-23T00:00:00Z",
    payload: { report_id: "report_001", title: "A report", revised },
  };
}

function renderGate(pending: PendingGate = gate()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReportGate runId="run_001" gate={pending} />
    </QueryClientProvider>,
  );
}

describe("ReportGate", () => {
  beforeEach(() => {
    mocks.confirmGate.mockReset();
    mocks.confirmGate.mockResolvedValue({});
  });

  it("accepts the report as final", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.click(screen.getByRole("button", { name: /accept report/i }));

    expect(mocks.confirmGate).toHaveBeenCalledWith("run_001", { decision: "accept" });
  });

  it("sends a rewrite instruction and promises no new searches", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.click(screen.getByRole("button", { name: /change something/i }));
    expect(screen.getByText(/no new searches/i)).toBeInTheDocument();

    await user.type(
      screen.getByLabelText(/what to change about the report/i),
      "Lead with the cost comparison",
    );
    await user.click(screen.getByRole("button", { name: /re-write it/i }));

    expect(mocks.confirmGate).toHaveBeenCalledWith("run_001", {
      decision: "rewrite",
      instruction: "Lead with the cost comparison",
    });
  });

  it("will not send an empty rewrite instruction", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.click(screen.getByRole("button", { name: /change something/i }));

    expect(screen.getByRole("button", { name: /re-write it/i })).toBeDisabled();
  });

  it("says when the draft has already been re-written once", () => {
    renderGate(gate(true));
    expect(screen.getByText(/re-written from the same findings/i)).toBeInTheDocument();
  });
});
