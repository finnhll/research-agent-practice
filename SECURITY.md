# Security Policy

## Supported versions

This project is pre-1.0 and currently in active design/development. Security fixes will target the latest `main` branch.

## Reporting a vulnerability

Please report vulnerabilities using GitHub's private security advisory feature:

1. Open the repository on GitHub.
2. Select the **Security** tab.
3. Choose **Report a vulnerability**.

If that option is unavailable, contact the repository owner through a private GitHub message.

Do not open a public issue for a suspected vulnerability.

## Security expectations

- Model API keys are supplied through environment variables or saved to
  `model-config.json`, which is gitignored. The API returns only a masked preview
  of a stored key and never the key itself.
- Do not commit `.env` files or `model-config.json`.
- Web content is untrusted input.
- Tool output must never be interpreted as system instructions.
- Model output is also untrusted, because it may have absorbed fetched web
  content. It is rendered through escaped text nodes, and any URL is restricted
  to `http`/`https` before becoming a link — a source URL of `javascript:...`
  would otherwise be a live click target in the dashboard and in the exported
  HTML report.
- Page fetching must use timeouts, response-size limits, an allowlist of content
  types, and must refuse private and loopback addresses.
- Guardrail decisions and unsafe-input handling must be logged.

## Scope

The project is not yet production-ready. It should not be used as a safety-critical system until it has completed the security review milestone in the design specification.
