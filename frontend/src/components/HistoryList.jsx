import { plural } from "../lib/format.js";

function describe(operation) {
  const { stats, kind, columns } = operation;
  if (kind === "derive") return `New column ${columns.at(-1)} from ${columns[0]}`;
  const where = columns.join(", ");
  return `${plural(stats.cells_changed ?? 0, "cell")} changed in ${where}`;
}

/** Applied operations, newest first, with undo and reset. */
export default function HistoryList({ operations, busy, onUndo, onReset }) {
  const newestFirst = [...operations].reverse();

  return (
    <section className="history" aria-labelledby="history-title">
      <div className="history__head">
        <h2 id="history-title" className="history__title">
          Changes
        </h2>
        <div className="history__actions">
          <button type="button" className="link-button" onClick={onUndo} disabled={busy || operations.length === 0}>
            Undo last
          </button>
          <button type="button" className="link-button" onClick={onReset} disabled={busy || operations.length === 0}>
            Restore original
          </button>
        </div>
      </div>

      {operations.length === 0 ? (
        <p className="history__empty">Nothing changed yet. Every change you apply is listed here and can be undone.</p>
      ) : (
        <ol className="history__list" reversed>
          {newestFirst.map((operation) => (
            <li key={operation.id} className="history__item">
              <p className="history__kind">{operation.kind_label}</p>
              {operation.instruction && <p className="history__instruction">{operation.instruction}</p>}
              {operation.pattern && (
                <code className="history__pattern">
                  {operation.pattern}
                  {operation.replacement !== "" ? `  →  ${operation.replacement}` : "  →  (deleted)"}
                </code>
              )}
              <p className="history__stats">{describe(operation)}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
