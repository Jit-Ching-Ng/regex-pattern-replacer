import { useMemo } from "react";

import { formatNumber } from "../lib/format.js";

const PAGE_SIZES = [25, 50, 100, 250];

/** The current version of the data, one page at a time, with changed cells marked. */
export default function DataTable({
  table,
  loading,
  error,
  page,
  pageSize,
  highlight,
  canHighlight,
  onPageChange,
  onPageSizeChange,
  onHighlightChange,
}) {
  const changed = useMemo(() => new Set((table?.changed ?? []).map(([row, column]) => `${row}:${column}`)), [table]);

  if (error && !table) {
    return (
      <div className="sheet__state" role="alert">
        <p>The rows could not be loaded: {error.message}</p>
      </div>
    );
  }
  if (!table) {
    return <div className="sheet__state" role="status">Loading rows…</div>;
  }

  const { columns, rows, offset, total_rows: totalRows, total_pages: totalPages } = table;
  const first = totalRows === 0 ? 0 : offset + 1;
  const last = offset + rows.length;

  return (
    <div className={`sheet__inner${loading ? " is-loading" : ""}`} aria-busy={loading}>
      <div className="sheet__bar">
        <label className={`check${canHighlight ? "" : " is-disabled"}`}>
          <input
            type="checkbox"
            checked={highlight && canHighlight}
            disabled={!canHighlight}
            onChange={(event) => onHighlightChange(event.target.checked)}
          />
          <span className="mark-sample" aria-hidden="true" />
          Mark cells changed by the last step
          {highlight && canHighlight && changed.size > 0 && (
            <span className="sheet__count">({formatNumber(changed.size)} on this page)</span>
          )}
        </label>
      </div>

      <div className="grid-scroll" tabIndex={0} aria-label="Table data, scrollable">
        <table className="grid">
          <thead>
            <tr>
              <th scope="col" className="grid__rownum">
                <span className="visually-hidden">Row</span>
              </th>
              {columns.map((column) => (
                <th key={column.name} scope="col">
                  <span className="grid__colname">{column.name}</span>
                  {column.kind !== "text" && <span className="grid__kind">{column.kind}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="grid__empty" colSpan={columns.length + 1}>
                  This file has headers but no rows.
                </td>
              </tr>
            ) : (
              rows.map((row, rowIndex) => (
                <tr key={offset + rowIndex}>
                  <th scope="row" className="grid__rownum">
                    {formatNumber(offset + rowIndex + 1)}
                  </th>
                  {row.map((value, columnIndex) => {
                    const isChanged = highlight && changed.has(`${rowIndex}:${columnIndex}`);
                    return (
                      <td key={columnIndex} className={isChanged ? "is-changed" : undefined} title={value.length > 60 ? value : undefined}>
                        {value}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <nav className="pager" aria-label="Pagination">
        <p className="pager__range">
          Rows {formatNumber(first)}–{formatNumber(last)} of {formatNumber(totalRows)}
        </p>
        <div className="pager__controls">
          <label className="pager__size">
            Rows per page
            <select className="input input--small" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="button button--quiet" onClick={() => onPageChange(1)} disabled={page <= 1}>
            First
          </button>
          <button type="button" className="button button--quiet" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
            Previous
          </button>
          <span className="pager__page">
            Page {formatNumber(page)} of {formatNumber(totalPages)}
          </span>
          <button type="button" className="button button--quiet" onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}>
            Next
          </button>
          <button type="button" className="button button--quiet" onClick={() => onPageChange(totalPages)} disabled={page >= totalPages}>
            Last
          </button>
        </div>
      </nav>
    </div>
  );
}
