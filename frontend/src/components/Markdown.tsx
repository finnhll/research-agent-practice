import type { ReactNode } from "react";

/**
 * Minimal, safe markdown rendering: everything goes through JSX text nodes (React
 * escapes them automatically), never dangerouslySetInnerHTML. The report text this
 * renders is model-generated and may have absorbed untrusted web content via tool
 * calls, so raw-HTML injection is never on the table here.
 */

const TOKEN_PATTERN = /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|`[^`]+`|\[\d+\])/g;

export function renderInline(text: string, citationLabels?: Set<string>): ReactNode[] {
  const parts = text.split(TOKEN_PATTERN).filter((part) => part !== "");
  return parts.map((part, index) => {
    const key = `${index}-${part.slice(0, 12)}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (
      (part.startsWith("*") && part.endsWith("*") && part.length > 2) ||
      (part.startsWith("_") && part.endsWith("_") && part.length > 2)
    ) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    const citation = /^\[(\d+)\]$/.exec(part);
    if (citation && citationLabels?.has(citation[1])) {
      return (
        <a key={key} className="citation-ref" href={`#source-${citation[1]}`}>
          [{citation[1]}]
        </a>
      );
    }
    return part;
  });
}

export function Prose({
  text,
  citationLabels,
}: {
  text: string;
  citationLabels?: Set<string>;
}) {
  const blocks = text.trim().split(/\n{2,}/).filter(Boolean);
  if (blocks.length === 0) return null;

  return (
    <>
      {blocks.map((block, blockIndex) => {
        const lines = block
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        const isBulleted = lines.length > 0 && lines.every((line) => /^[-*]\s+/.test(line));
        const isNumbered = lines.length > 0 && lines.every((line) => /^\d+[.)]\s+/.test(line));

        if (isBulleted) {
          return (
            <ul key={blockIndex}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {renderInline(line.replace(/^[-*]\s+/, ""), citationLabels)}
                </li>
              ))}
            </ul>
          );
        }
        if (isNumbered) {
          return (
            <ol key={blockIndex}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {renderInline(line.replace(/^\d+[.)]\s+/, ""), citationLabels)}
                </li>
              ))}
            </ol>
          );
        }
        return <p key={blockIndex}>{renderInline(lines.join(" "), citationLabels)}</p>;
      })}
    </>
  );
}

interface ParsedTable {
  headers: string[];
  rows: string[][];
}

function parsePipeTable(markdown: string): ParsedTable | null {
  const lines = markdown
    .trim()
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) return null;

  const splitRow = (line: string) =>
    line
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());

  const headers = splitRow(lines[0]);
  if (!/^[\s|:-]+$/.test(lines[1])) return null;

  const rows = lines.slice(2).map(splitRow);
  return { headers, rows };
}

export function ComparisonTable({ markdown }: { markdown: string }) {
  const table = parsePipeTable(markdown);
  if (!table) {
    return <pre className="comparison-fallback">{markdown}</pre>;
  }
  return (
    <div className="table-scroll">
      <table className="comparison-table">
        <thead>
          <tr>
            {table.headers.map((header, index) => (
              <th key={index}>{renderInline(header)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{renderInline(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
