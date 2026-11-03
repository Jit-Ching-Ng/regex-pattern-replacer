/**
 * Toggle chips for target columns. An empty selection means
 * "every text column", which is also what the API does by default.
 */
export default function ColumnPicker({ columns, selected, onChange, label = "Columns to search" }) {
  const toggle = (name) =>
    onChange(selected.includes(name) ? selected.filter((item) => item !== name) : [...selected, name]);

  return (
    <fieldset className="field column-picker">
      <legend className="field__label">{label}</legend>
      <div className="chips">
        <button
          type="button"
          className="chip"
          aria-pressed={selected.length === 0}
          onClick={() => onChange([])}
        >
          All text columns
        </button>
        {columns.map((column) => (
          <button
            key={column.name}
            type="button"
            className="chip"
            aria-pressed={selected.includes(column.name)}
            onClick={() => toggle(column.name)}
            title={column.kind === "text" ? undefined : `${column.kind} column`}
          >
            {column.name}
            {column.kind !== "text" && <span className="chip__kind">{column.kind === "numeric" ? "123" : "empty"}</span>}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
