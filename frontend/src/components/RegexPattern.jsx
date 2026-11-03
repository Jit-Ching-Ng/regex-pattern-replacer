import { tokenizeRegex } from "../lib/regexTokens.js";

const FLAG_LABELS = { IGNORECASE: "Ignore case", MULTILINE: "Multiline", DOTALL: "Dot matches newline" };

/** The generated regex, syntax-coloured, with an inline editor. */
export default function RegexPattern({ pattern, flags, explanation, editing, onEdit, onPatternChange, onFlagsChange }) {
  const toggleFlag = (flag) =>
    onFlagsChange(flags.includes(flag) ? flags.filter((item) => item !== flag) : [...flags, flag]);

  return (
    <div className="pattern">
      <div className="pattern__head">
        <span className="field__label" id="pattern-label">
          Regex
        </span>
        <button type="button" className="link-button" onClick={onEdit}>
          {editing ? "Done editing" : "Edit"}
        </button>
      </div>

      {editing ? (
        <textarea
          className="pattern__editor"
          aria-labelledby="pattern-label"
          value={pattern}
          spellCheck={false}
          rows={3}
          onChange={(event) => onPatternChange(event.target.value)}
        />
      ) : (
        <code className="pattern__code" aria-labelledby="pattern-label">
          {tokenizeRegex(pattern).map((token, index) => (
            <span key={index} className={`tok tok--${token.type}`}>
              {token.text}
            </span>
          ))}
        </code>
      )}

      {explanation && !editing && <p className="pattern__explain">{explanation}</p>}

      <div className="flags" role="group" aria-label="Regex options">
        {Object.entries(FLAG_LABELS).map(([flag, label]) => (
          <label key={flag} className="check">
            <input type="checkbox" checked={flags.includes(flag)} onChange={() => toggleFlag(flag)} />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}
