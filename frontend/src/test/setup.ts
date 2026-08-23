import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

// jsdom has no EventSource, and the live-progress hook opens one for any running
// run. A no-op stub keeps component tests focused on rendering rather than SSE.
class EventSourceStub {
  onopen: (() => void) | null = null;
  addEventListener(): void {}
  removeEventListener(): void {}
  close(): void {}
}

vi.stubGlobal("EventSource", EventSourceStub);
