# Contributing

Thanks for helping improve the Research & Report Agent.

## Development setup

1. Install Python 3.11 or newer.
2. Clone the repository.
3. Create and activate a virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

4. Install the development dependencies:

```bash
python -m pip install -e ".[dev]"
```

5. Install the frontend dependencies (Node 20 or newer):

```bash
cd frontend
npm install
```

`./scripts/dev.sh` runs both services together once this is done.

## Workflow

1. Create a feature branch from `main`.
2. Make a focused change.
3. Add or update tests.
4. Run all quality checks locally. CI runs the same three jobs, so a change that
   touches both sides has to pass both:

```bash
ruff format --check .
ruff check .
pytest
```

```bash
cd frontend
npm run typecheck
npm run test -- --run
npm run build
```

5. Push your branch.
6. Open a pull request into `main`.
7. Wait for CI and code review to pass.
8. Use a squash merge so `main` retains linear history.

## Commit message conventions

Use the Conventional Commits format:

```text
type: short imperative description
```

Common types:

- `feat`: new user-facing capability
- `fix`: bug fix
- `docs`: documentation
- `test`: tests only
- `refactor`: behavior-preserving code change
- `chore`: tooling or maintenance
- `ci`: CI changes

## Design changes

Architecture-first changes should update `docs/spec/design.md` before implementation.
`docs/spec/design.zh-CN.md` tracks it; update it in the same pull request when the
architecture changes, or say in the PR that it is intentionally left behind.
Describe:

- The affected component
- New contracts
- Failure states
- Retry and termination behavior
- Tests

## Code review expectations

- Public functions have type hints.
- Models are Pydantic types.
- Agent outputs are validated before use.
- Every loop has a termination condition.
- Factual output is tied to source IDs.
- New behavior has tests.

Frontend specifics:

- No colour literals in component CSS. Every colour comes from a token defined in
  all three theme blocks (see design spec §24), or it will be wrong in one theme.
- Report and source text is model-generated and may carry fetched web content.
  Render it through JSX text nodes, never `dangerouslySetInnerHTML`, and pass any
  URL through `safeHref` before it becomes an `href`.
- A new `RunPhase` must be added to `PHASE_TO_STAGE`. A phase missing from that
  map silently blanks the whole progress spine rather than erroring.

## Security

Do not commit API keys, browser sessions, logs, or private research data.
Report security vulnerabilities through [SECURITY.md](SECURITY.md) rather than public issues.
