import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { RunMode } from "./types";
import type { Run } from "./types";
import ChatComposer from "./components/ChatComposer";
import ModelSettings from "./components/ModelSettings";
import RunRail from "./components/RunRail";
import RunWorkspace from "./components/RunWorkspace";

const EXAMPLES = [
  "How are mid-size banks actually deploying LLMs in production today?",
  "Compare heat pump economics in cold climates versus gas furnaces",
  "What's the state of solid-state battery commercialisation in 2026?",
];

export default function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Holds a run we just created or restarted, so the workspace can open even if
  // the runs list has not caught up yet. Never trust list timing for navigation.
  const [pendingRun, setPendingRun] = useState<Run | null>(null);
  const [composing, setComposing] = useState(true);
  const [traceOpen, setTraceOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<RunMode>("guided");
  const queryClient = useQueryClient();

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
    refetchInterval: 4000,
  });

  const createRun = useMutation({
    mutationFn: ({ goal, dimensions }: { goal: string; dimensions: string[] }) =>
      api.createRun(goal, dimensions, mode),
    onSuccess: (run) => {
      // Seed the cache before switching. invalidateQueries only *schedules* a
      // refetch, so without this the stale-selection guard below runs against a
      // list that does not contain the new run yet and bounces straight back to
      // the composer -- which is what kept the user stuck on this screen.
      queryClient.setQueryData<Run[]>(["runs"], (current) =>
        current
          ? [run, ...current.filter((item) => item.run_id !== run.run_id)]
          : [run],
      );
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      setPendingRun(run);
      setSelectedId(run.run_id);
      setComposing(false);
      setRailOpen(false);
      setTraceOpen(false);
    },
  });

  const runs = [...(runsQuery.data ?? [])].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  // Keep the selection pointing at something real as runs come and go, but never
  // judge a list that is still loading -- an in-flight refetch is not evidence
  // that the selected run is gone.
  useEffect(() => {
    if (!selectedId || runsQuery.isFetching) return;
    if (pendingRun?.run_id === selectedId) return;
    if (!runs.some((run) => run.run_id === selectedId)) {
      setSelectedId(null);
      setComposing(true);
    }
  }, [runs, selectedId, runsQuery.isFetching, pendingRun]);

  // Once the list catches up, the list copy is the fresher one.
  const selected =
    runs.find((run) => run.run_id === selectedId) ??
    (pendingRun?.run_id === selectedId ? pendingRun : null);
  const showWorkspace = !composing && selected !== null;

  function openNew() {
    setComposing(true);
    setSelectedId(null);
    setPendingRun(null);
    setRailOpen(false);
    setTraceOpen(false);
  }

  function selectRun(runId: string) {
    setPendingRun(null);
    setSelectedId(runId);
    setComposing(false);
    setRailOpen(false);
  }

  const shellClass = [
    "app",
    showWorkspace && traceOpen ? "inspect" : "",
    railOpen ? "railopen" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClass}>
      <RunRail
        runs={runs}
        selectedId={selectedId}
        onSelect={selectRun}
        onNew={openNew}
        onOpenSettings={() => setSettingsOpen(true)}
        onDeleted={(runId) => {
          // Deleting whatever is on screen has to leave somewhere valid.
          if (runId === selectedId) {
            setSelectedId(null);
            setComposing(true);
            setTraceOpen(false);
          }
        }}
        loading={runsQuery.isLoading}
      />

      {railOpen ? (
        <button
          className="rail-scrim"
          onClick={() => setRailOpen(false)}
          aria-label="Close run list"
        />
      ) : null}

      {showWorkspace ? (
        <RunWorkspace
          key={selected.run_id}
          run={selected}
          traceOpen={traceOpen}
          onToggleTrace={() => setTraceOpen((open) => !open)}
          onToggleRail={() => setRailOpen((open) => !open)}
          onRestarted={(fresh) => {
            queryClient.setQueryData<Run[]>(["runs"], (current) =>
              current
                ? [fresh, ...current.filter((item) => item.run_id !== fresh.run_id)]
                : [fresh],
            );
            setPendingRun(fresh);
            setSelectedId(fresh.run_id);
            setComposing(false);
            setTraceOpen(false);
          }}
        />
      ) : (
        <main className="work">
          <div className="topbar">
            <button
              className="tbtn railtoggle"
              onClick={() => setRailOpen((open) => !open)}
              aria-label="Show runs"
            >
              ☰
            </button>
            <h1>New question</h1>
          </div>
          <div className="canvas">
            <div className="sheet">
              <div className="hello">
                <h2>What do you want researched?</h2>
                {/* What the agent does is now introduced inside the box itself,
                    so repeating it here would say the same thing twice. */}

                <ChatComposer
                  submitting={createRun.isPending}
                  value={draft}
                  onValueChange={setDraft}
                  onSubmit={(goal, dimensions) => {
                    createRun.mutate({ goal, dimensions });
                    setDraft("");
                  }}
                />
                {createRun.isError ? (
                  <p className="error composer-error">
                    {(createRun.error as Error).message}
                  </p>
                ) : null}

                <div className="mode-row">
                  <div className="mode-toggle" role="group" aria-label="How much to ask">
                    <button
                      className={mode === "guided" ? "on" : ""}
                      aria-pressed={mode === "guided"}
                      onClick={() => setMode("guided")}
                    >
                      Guided
                    </button>
                    <button
                      className={mode === "autonomous" ? "on" : ""}
                      aria-pressed={mode === "autonomous"}
                      onClick={() => setMode("autonomous")}
                    >
                      Autonomous
                    </button>
                  </div>
                  <span>
                    {mode === "guided"
                      ? "I'll confirm the question with you before researching"
                      : "I'll research straight through without stopping"}
                  </span>
                </div>

                <div className="examples">
                  <div className="ex-label">Or start from one of these</div>
                  {EXAMPLES.map((example) => (
                    <button
                      className="ex"
                      key={example}
                      onClick={() => setDraft(example)}
                    >
                      {example}
                    </button>
                  ))}
                </div>

                {runsQuery.isError ? (
                  <p className="error">{(runsQuery.error as Error).message}</p>
                ) : null}
              </div>
            </div>
          </div>
        </main>
      )}

      {settingsOpen ? (
        <div className="modal-scrim" role="presentation">
          <div className="modal">
            <ModelSettings onClose={() => setSettingsOpen(false)} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
