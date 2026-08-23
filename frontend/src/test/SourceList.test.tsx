import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SourceList from "../components/SourceList";
import { safeHref } from "../lib/url";
import type { SourceRecord } from "../types";

function source(overrides: Partial<SourceRecord>): SourceRecord {
  return {
    source_id: "src",
    title: "A source",
    url: "https://example.com",
    publisher: "Publisher",
    published_at: null,
    retrieved_at: "2026-08-21T00:00:00Z",
    credibility: "medium",
    notes: null,
    ...overrides,
  };
}

describe("safeHref", () => {
  it("passes http(s) through and rejects everything else", () => {
    expect(safeHref("https://example.com")).toBe("https://example.com");
    expect(safeHref("http://example.com")).toBe("http://example.com");
    expect(safeHref("  https://example.com  ")).toBe("https://example.com");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("JavaScript:alert(1)")).toBeNull();
    expect(safeHref("  javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>")).toBeNull();
    expect(safeHref("")).toBeNull();
    expect(safeHref(null)).toBeNull();
  });
});

describe("SourceList", () => {
  it("links safe URLs", () => {
    render(<SourceList sources={[source({ source_id: "a", title: "Good" })]} />);
    expect(screen.getByRole("link", { name: "Good" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
  });

  it("shows an unsafe URL as text rather than a clickable link", () => {
    render(
      <SourceList
        sources={[source({ source_id: "b", title: "Bad", url: "javascript:alert(1)" })]}
      />,
    );
    // The title is still readable, but it is not a link.
    expect(screen.getByText("Bad")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bad" })).not.toBeInTheDocument();
  });
});
