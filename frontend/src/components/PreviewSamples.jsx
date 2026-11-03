import { formatNumber, plural } from "../lib/format.js";

/** Before/after examples from a dry run, so users can check the pattern before applying it. */
export default function PreviewSamples({ preview, stale }) {
  if (!preview) return null;
  const { matches, cells_changed: cellsChanged, columns, samples } = preview;

  return (
    <div className={`preview${stale ? " is-stale" : ""}`} aria-live="polite">
      <p className="preview__summary">
        {matches === 0 ? (
          <>No matches in {columns.join(", ")}.</>
        ) : (
          <>
            <strong>{plural(matches, "match", "matches")}</strong> in {plural(cellsChanged, "cell")} across{" "}
            {columns.join(", ")}.
          </>
        )}
        {stale && " Settings changed since this preview."}
      </p>
      {samples.length > 0 && (
        <ul className="preview__list">
          {samples.map((sample) => (
            <li key={`${sample.row}-${sample.column}`} className="preview__item">
              <span className="preview__where">
                Row {formatNumber(sample.row + 1)}, {sample.column}
              </span>
              <del className="preview__before">{sample.before}</del>
              <ins className="preview__after">{sample.after === "" ? "(empty)" : sample.after}</ins>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
