import { useEffect, useRef, useState } from "react";

/**
 * Lenses, not topics. A dimension becomes a coverage contract: the planner must
 * spend a task on it and the critic reports it under missing_dimensions, so these
 * have to apply to almost any question. Anything narrower goes in via "Add focus".
 */
const DIMENSIONS = ["cost", "risks", "tradeoffs", "alternatives", "track record"];

/**
 * The API allows up to 5 (RunCreateRequest.dimensions), but the planner only ever
 * produces 3-6 tasks, so each dimension it is told to cover claims one of them.
 * Two keeps the user's angles honoured while leaving the planner room to decompose
 * the question itself.
 */
const MAX_DIMENSIONS = 2;

export default function ChatComposer({
  onSubmit,
  submitting,
  value,
  onValueChange,
}: {
  onSubmit: (goal: string, dimensions: string[]) => void;
  submitting: boolean;
  /** Controlled when provided, so the example prompts can fill the box. */
  value?: string;
  onValueChange?: (next: string) => void;
}) {
  const [internalGoal, setInternalGoal] = useState("");
  const goal = value ?? internalGoal;
  const setGoal = onValueChange ?? setInternalGoal;
  const [selected, setSelected] = useState<string[]>([]);
  const [customDraft, setCustomDraft] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const atLimit = selected.length >= MAX_DIMENSIONS;
  const custom = selected.filter((item) => !DIMENSIONS.includes(item));

  function toggleDimension(dimension: string) {
    setSelected((current) =>
      current.includes(dimension)
        ? current.filter((item) => item !== dimension)
        : current.length >= MAX_DIMENSIONS
          ? current
          : [...current, dimension],
    );
  }

  function commitCustom() {
    const value = (customDraft ?? "").trim().toLowerCase();
    if (!value || atLimit || selected.includes(value)) {
      setCustomDraft(null);
      return;
    }
    setSelected((current) => [...current, value]);
    setCustomDraft(null);
  }

  useEffect(autoGrow, [goal]);

  function autoGrow() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    // While empty, let CSS own the resting height. Measuring at mount can happen
    // before layout settles, and a bad measurement would stick until the next
    // keystroke.
    if (!el.value) return;
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }

  function send() {
    const trimmed = goal.trim();
    if (trimmed.length < 3 || submitting) return;
    onSubmit(trimmed, selected);
    setGoal("");
    requestAnimationFrame(autoGrow);
  }

  return (
    <div className="composer">
      <div className="composer-focus">
        <span className="focus-eyebrow">Focus</span>
        <span className="focus-rule" aria-hidden="true" />
        <div className="composer-dimensions">
        {DIMENSIONS.map((dimension) => {
          const active = selected.includes(dimension);
          return (
            <button
              key={dimension}
              type="button"
              className={`chip ${active ? "chip-active" : ""}`}
              aria-pressed={active}
              disabled={!active && atLimit}
              onClick={() => toggleDimension(dimension)}
            >
              {dimension}
            </button>
          );
        })}

        {custom.map((dimension) => (
          <button
            key={dimension}
            type="button"
            className="chip chip-active chip-custom"
            aria-label={`Remove focus ${dimension}`}
            onClick={() => toggleDimension(dimension)}
          >
            {dimension}
            <span aria-hidden="true">&times;</span>
          </button>
        ))}

        {customDraft === null ? (
          <button
            type="button"
            className="chip chip-add"
            disabled={atLimit}
            title={atLimit ? `Up to ${MAX_DIMENSIONS} focus areas` : undefined}
            onClick={() => setCustomDraft("")}
          >
            + Add focus
          </button>
        ) : (
          <input
            className="chip chip-input"
            autoFocus
            value={customDraft}
            aria-label="Add a focus area"
            placeholder="e.g. regulation"
            maxLength={40}
            onChange={(event) => setCustomDraft(event.target.value)}
            onBlur={commitCustom}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitCustom();
              } else if (event.key === "Escape") {
                setCustomDraft(null);
              }
            }}
            />
          )}
        </div>
        <span className={`focus-counter ${atLimit ? "at-limit" : ""}`}>
          {atLimit ? `${MAX_DIMENSIONS} of ${MAX_DIMENSIONS} — deselect to swap` : `${selected.length} of ${MAX_DIMENSIONS}`}
        </span>
      </div>

      <div className="composer-input-row">
        <textarea
          ref={textareaRef}
          className="composer-input"
          value={goal}
          rows={1}
          aria-label="Research goal"
          placeholder="Ask a research question — e.g. Compare Rust and Go for a new backend service."
          onChange={(event) => {
            setGoal(event.target.value);
            autoGrow();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button
          type="button"
          className="composer-send"
          onClick={send}
          disabled={goal.trim().length < 3 || submitting}
          aria-label="Send"
        >
          {submitting ? <span className="spinner" /> : "↑"}
        </button>
      </div>
    </div>
  );
}
