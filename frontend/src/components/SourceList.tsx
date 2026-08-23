import type { SourceRecord } from "../types";
import { safeHref } from "../lib/url";

export default function SourceList({ sources }: { sources: SourceRecord[] }) {
  return (
    <ol className="source-list">
      {sources.map((source, index) => {
        const href = safeHref(source.url);
        const label = source.title || source.url;
        return (
        <li key={source.source_id} id={`source-${index + 1}`}>
          <span className="source-number">[{index + 1}]</span>
          <div className="source-body">
            {href ? (
              <a href={href} target="_blank" rel="noreferrer">
                {label}
              </a>
            ) : (
              <span className="source-inert">{label}</span>
            )}
            <small>
              {source.publisher}
              {source.credibility ? ` · credibility ${source.credibility}` : ""}
            </small>
          </div>
        </li>
        );
      })}
    </ol>
  );
}
