// Rich rendering of a successful agent answer: the generated SQL (collapsed by
// default) and the result rows as a scrollable table. The summary text lives in
// the bubble above this; here we show the evidence behind it.

import type { AgentResult } from "./types";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

export function ResultView({ result }: { result: AgentResult }) {
  const { sql, columns, rows, attempts } = result;

  return (
    <div className="result">
      {attempts > 1 && (
        <div className="attempts">self-corrected after {attempts} attempts</div>
      )}

      {sql && (
        <details className="sql">
          <summary>SQL</summary>
          <pre>
            <code>{sql}</code>
          </pre>
        </details>
      )}

      {rows.length > 0 && (
        <details className="table-details">
          <summary>
            Results ({rows.length} row{rows.length === 1 ? "" : "s"})
          </summary>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((value, j) => (
                      <td key={j}>{cell(value)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
