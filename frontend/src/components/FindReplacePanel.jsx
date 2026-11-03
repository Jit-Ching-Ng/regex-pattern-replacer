import { useMemo, useState } from "react";

import { api } from "../api/client.js";
import { plural } from "../lib/format.js";
import ColumnPicker from "./ColumnPicker.jsx";
import PreviewSamples from "./PreviewSamples.jsx";
import RegexPattern from "./RegexPattern.jsx";

const EXAMPLES = [
  "Find email addresses in the Email column and replace them with 'REDACTED'",
  "Phone numbers in any format",
  "Dates written like 2023-01-15",
  "Web links starting with http or https",
  "16-digit card numbers, with or without spaces",
];

/**
 * The core flow of the brief:
 *   1. describe a pattern in plain English (+ optional replacement / columns)
 *   2. the backend asks the LLM for a regex and returns a dry-run preview
 *   3. the user can tweak the regex, options or replacement and re-preview
 *   4. apply, which records an operation and refreshes the table
 */
export default function FindReplacePanel({ dataset, onApplied }) {
  const [instruction, setInstruction] = useState("");
  const [replacement, setReplacement] = useState("");
  const [columns, setColumns] = useState([]);
  const [useBackrefs, setUseBackrefs] = useState(false);

  const [pattern, setPattern] = useState("");
  const [flags, setFlags] = useState([]);
  const [explanation, setExplanation] = useState("");
  const [editing, setEditing] = useState(false);

  const [preview, setPreview] = useState(null);
  const [previewKey, setPreviewKey] = useState(null);
  const [busy, setBusy] = useState(null); // "suggest" | "preview" | "apply" | null
  const [error, setError] = useState(null);

  const spec = useMemo(
    () => ({ pattern, flags, replacement, columns, use_backrefs: useBackrefs }),
    [pattern, flags, replacement, columns, useBackrefs],
  );
  const specKey = JSON.stringify(spec);
  const stale = Boolean(preview) && previewKey !== specKey;

  const run = async (kind, task) => {
    setBusy(kind);
    setError(null);
    try {
      await task();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(null);
    }
  };

  const generate = (event) => {
    event.preventDefault();
    if (!instruction.trim()) {
      setError("Describe the pattern you want to find first.");
      return;
    }
    run("suggest", async () => {
      const body = await api.suggestRegex(dataset.id, {
        instruction,
        columns,
        // An empty field lets the backend use a replacement stated in the sentence.
        replacement: replacement === "" ? null : replacement,
        use_backrefs: useBackrefs,
      });
      const { suggestion } = body;
      const nextReplacement = replacement === "" && suggestion.replacement ? suggestion.replacement : replacement;
      const nextColumns = columns.length ? columns : suggestion.columns;
      setPattern(suggestion.pattern);
      setFlags(suggestion.flags);
      setExplanation(suggestion.explanation);
      setReplacement(nextReplacement);
      setColumns(nextColumns);
      setEditing(false);
      setPreview(body.preview);
      setPreviewKey(
        JSON.stringify({
          pattern: suggestion.pattern,
          flags: suggestion.flags,
          replacement: nextReplacement,
          columns: nextColumns,
          use_backrefs: useBackrefs,
        }),
      );
    });
  };

  const refreshPreview = () =>
    run("preview", async () => {
      const body = await api.previewRegex(dataset.id, spec);
      setPreview(body.preview);
      setPreviewKey(specKey);
    });

  const apply = () =>
    run("apply", async () => {
      const body = await api.applyRegex(dataset.id, { ...spec, instruction, explanation });
      const changed = body.operation.stats.cells_changed;
      onApplied(
        body.dataset,
        changed ? `Replaced matches in ${plural(changed, "cell")}.` : "The pattern matched nothing, so no cells changed.",
      );
      clearResult();
    });

  /** Hide the regex and preview once applied, so the same change can't be applied twice by accident.
   *  The description, replacement and columns stay, ready for a follow-up search. */
  const clearResult = () => {
    setPattern("");
    setFlags([]);
    setExplanation("");
    setEditing(false);
    setPreview(null);
    setPreviewKey(null);
  };

  const hasPattern = pattern.trim() !== "";

  return (
    <div className="panel">
      <form className="panel__form" onSubmit={generate}>
        <div className="field">
          <label className="field__label" htmlFor="instruction">
            What should be found?
          </label>
          <textarea
            id="instruction"
            className="input input--area"
            rows={3}
            maxLength={1000}
            placeholder="e.g. email addresses, or order numbers like AB-12345"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) generate(event);
            }}
          />
          <div className="examples" aria-label="Example descriptions">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" className="example" onClick={() => setInstruction(example)}>
                {example}
              </button>
            ))}
          </div>
        </div>

        <ColumnPicker columns={dataset.columns} selected={columns} onChange={setColumns} />

        <div className="field">
          <label className="field__label" htmlFor="replacement">
            Replace with
          </label>
          <input
            id="replacement"
            className="input"
            placeholder="Leave empty to delete matches"
            value={replacement}
            onChange={(event) => setReplacement(event.target.value)}
          />
          <label className="check">
            <input type="checkbox" checked={useBackrefs} onChange={(event) => setUseBackrefs(event.target.checked)} />
            Allow group references such as \1 in the replacement
          </label>
        </div>

        <button type="submit" className="button button--primary" disabled={busy !== null}>
          {busy === "suggest" ? "Finding matches…" : "Find matches"}
        </button>
      </form>

      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}

      {hasPattern && (
        <div className="panel__result">
          <RegexPattern
            pattern={pattern}
            flags={flags}
            explanation={explanation}
            editing={editing}
            onEdit={() => setEditing((value) => !value)}
            onPatternChange={(value) => {
              setPattern(value);
              setExplanation("");
            }}
            onFlagsChange={setFlags}
          />

          <PreviewSamples preview={preview} stale={stale} />

          <div className="panel__actions">
            {(stale || !preview) && (
              <button type="button" className="button" onClick={refreshPreview} disabled={busy !== null}>
                {busy === "preview" ? "Checking…" : "Preview changes"}
              </button>
            )}
            <button
              type="button"
              className="button button--primary"
              onClick={apply}
              disabled={busy !== null || Boolean(preview && !stale && preview.matches === 0)}
            >
              {busy === "apply"
                ? "Replacing…"
                : preview && !stale && preview.matches > 0
                  ? `Replace ${plural(preview.matches, "match", "matches")}`
                  : "Replace matches"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
