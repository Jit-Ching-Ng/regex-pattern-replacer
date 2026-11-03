import { api } from "../api/client.js";
import { formatBytes, plural } from "../lib/format.js";

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="5" y="5" width="22" height="22" rx="4" transform="rotate(45 16 16)" />
      <rect className="brand-mark__core" x="11.5" y="11.5" width="9" height="9" rx="1.5" transform="rotate(45 16 16)" />
    </svg>
  );
}

export default function Toolbar({ dataset, onClose }) {
  return (
    <header className="toolbar">
      <div className="toolbar__file">
        <BrandMark />
        <div>
          <h1 className="toolbar__name" title={dataset.name}>
            {dataset.name}
          </h1>
          <p className="toolbar__meta">
            {plural(dataset.row_count, "row")}, {plural(dataset.columns.length, "column")}, {formatBytes(dataset.size_bytes)}
          </p>
        </div>
      </div>
      <nav className="toolbar__actions" aria-label="File actions">
        <a className="button button--quiet" href={api.exportUrl(dataset.id, "csv")} download>
          Download CSV
        </a>
        <a className="button button--quiet" href={api.exportUrl(dataset.id, "xlsx")} download>
          Download Excel
        </a>
        <button type="button" className="button button--quiet" onClick={onClose}>
          Open another file
        </button>
      </nav>
    </header>
  );
}
