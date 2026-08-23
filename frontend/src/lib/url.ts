/**
 * Source URLs arrive from model output and fetched web content, so they are
 * untrusted. React warns about `javascript:` hrefs but still renders them, and
 * a link that executes script would run in this app's own origin. Only plain
 * http(s) becomes a live link; anything else is shown as inert text.
 */
export function safeHref(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const candidate = raw.trim();
  const lowered = candidate.toLowerCase();
  return lowered.startsWith("http://") || lowered.startsWith("https://") ? candidate : null;
}
