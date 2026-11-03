import { useState } from "react";

import { api } from "../api/client.js";
import { plural } from "../lib/format.js";

const MODES = {
  standardize: {
    label: "Clean up a column",
    help: "Rewrites the values of one column in place.",
    placeholder: "e.g. convert every date to YYYY-MM-DD",
    examples: ["Convert every date to YYYY-MM-DD", "Format phone numbers as +1 XXX-XXX-XXXX", "Title-case the names"],
    action: "Clean up column",
    busy: "Cleaning up…",
  },
  derive: {
    label: "Add a derived column",
    help: "Creates a new column next to the source, computed from each value.",
    placeholder: "e.g. classify the note as complaint, question or other",
    examples: [
      "The company name, taken from the email domain",
      "Classify the note as complaint, question or other",
      "The country this phone number belongs to",
    ],
    action: "Add column",
    busy: "Adding column…",
  },
};

/** The two optional LLM-powered transformations. */
export default function TransformPanel({ dataset, onApplied }) {
  const textColumns = dataset.columns.filter((column) => column.kind !== "empty");
  const [mode, setMode] = useState("standardize");
  const [column, setColumn] = useState(textColumns.find((item) => item.kind === "text")?.name ?? "");
  const [instruction, setInstruction] = useState("");
  const [newColumn, setNewColumn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [samples, setSamples] = useState([]);

  const copy = MODES[mode];

  const submit = async (event) => {
    event.preventDefault();
    if (!column || !instruction.trim()) {
      setError("Pick a column and describe the change.");
      return;
    }
    if (mode === "derive" && !newColumn.trim()) {
      setError("Name the new column.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = await api.transform(dataset.id, {
        kind: mode,
        column,
        instruction,
        new_column: mode === "derive" ? newColumn.trim() : "",
      });
      const { stats } = body.operation;
      setSamples(body.samples ?? []);
      const unresolved = stats.unresolved ? ` ${plural(stats.unresolved, "value")} could not be processed.` : "";
      onApplied(
        body.dataset,
        mode === "derive"
          ? `Added “${newColumn.trim()}”.${unresolved}`
          : `Cleaned up ${plural(stats.cells_changed, "cell")} in ${column}.${unresolved}`,
      );
      if (mode === "derive") setNewColumn("");
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="segmented" role="radiogroup" aria-label="Transformation">
        {Object.entries(MODES).map(([key, item]) => (
          <label key={key} className="segmented__option">
            <input
              type="radio"
              name="transform-mode"
              value={key}
              checked={mode === key}
              onChange={() => {
                setMode(key);
                setSamples([]);
                setError(null);
              }}
            />
            <span>{item.label}</span>
          </label>
        ))}
      </div>
      <p className="panel__help">
        {copy.help} The language model sees each distinct value of the column once, so this works best on columns
        with up to a few hundred distinct values.
      </p>

      <form className="panel__form" onSubmit={submit}>
        <div className="field">
          <label className="field__label" htmlFor="transform-column">
            {mode === "derive" ? "Source column" : "Column"}
          </label>
          <select
            id="transform-column"
            className="input"
            value={column}
            onChange={(event) => setColumn(event.target.value)}
          >
            {textColumns.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="transform-instruction">
            {mode === "derive" ? "What should the new column contain?" : "How should the values change?"}
          </label>
          <textarea
            id="transform-instruction"
            className="input input--area"
            rows={3}
            maxLength={1000}
            placeholder={copy.placeholder}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
          />
          <div className="examples" aria-label="Example instructions">
            {copy.examples.map((example) => (
              <button key={example} type="button" className="example" onClick={() => setInstruction(example)}>
                {example}
              </button>
            ))}
          </div>
        </div>

        {mode === "derive" && (
          <div className="field">
            <label className="field__label" htmlFor="new-column">
              New column name
            </label>
            <input
              id="new-column"
              className="input"
              maxLength={255}
              placeholder="e.g. Company"
              value={newColumn}
              onChange={(event) => setNewColumn(event.target.value)}
            />
          </div>
        )}

        <button type="submit" className="button button--primary" disabled={busy}>
          {busy ? copy.busy : copy.action}
        </button>
      </form>

      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}

      {samples.length > 0 && (
        <div className="preview">
          <p className="preview__summary">Examples from the last run</p>
          <ul className="preview__list">
            {samples.map((sample) => (
              <li key={sample.before} className="preview__item">
                {mode === "derive" ? (
                  <span className="preview__source">{sample.before}</span>
                ) : (
                  <del className="preview__before">{sample.before}</del>
                )}
                <ins className="preview__after">{sample.after === "" ? "(empty)" : sample.after}</ins>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
