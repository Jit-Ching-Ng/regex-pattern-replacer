/**
 * A small regex tokenizer used only for syntax colouring in the UI.
 * It does not validate anything; the backend is the source of truth.
 *
 * Token types: class (\d, \w, .), escape (\., \/), set ([a-z]), group,
 * quant (*, +, {2,7}), anchor (^, $, \b), alt (|), literal.
 */
const SPECIAL = "\\[]()*+?{}^$|.";

export function tokenizeRegex(source = "") {
  const tokens = [];
  const push = (type, text) => tokens.push({ type, text });
  let i = 0;

  while (i < source.length) {
    const ch = source[i];
    const rest = source.slice(i);

    if (ch === "\\") {
      let text = source.slice(i, i + 2);
      const unicodeProperty = rest.match(/^\\[pPN]\{[^}]*\}/);
      if (unicodeProperty) text = unicodeProperty[0];
      const type = /^\\[bBAZzG]/.test(text) ? "anchor" : /^\\[dDwWsSpPhHvVN]/.test(text) ? "class" : "escape";
      push(type, text);
      i += text.length;
      continue;
    }
    if (ch === "[") {
      let j = i + 1;
      if (source[j] === "^") j += 1;
      if (source[j] === "]") j += 1;
      while (j < source.length && source[j] !== "]") j += source[j] === "\\" ? 2 : 1;
      push("set", source.slice(i, j + 1));
      i = j + 1;
      continue;
    }
    if (ch === "(") {
      const opener = rest.match(/^\((\?(?:[:=!>|]|<[=!]|P?<[^>]+>|[a-zA-Z-]+:?))?/)[0];
      push("group", opener);
      i += opener.length;
      continue;
    }
    if (ch === ")") {
      push("group", ch);
      i += 1;
      continue;
    }
    if ("*+?".includes(ch)) {
      const text = "?+".includes(source[i + 1] ?? "") ? ch + source[i + 1] : ch;
      push("quant", text);
      i += text.length;
      continue;
    }
    const counted = ch === "{" && rest.match(/^\{\d*(?:,\d*)?\}[?+]?/);
    if (counted) {
      push("quant", counted[0]);
      i += counted[0].length;
      continue;
    }
    if (ch === "^" || ch === "$") {
      push("anchor", ch);
      i += 1;
      continue;
    }
    if (ch === "|") {
      push("alt", ch);
      i += 1;
      continue;
    }
    if (ch === ".") {
      push("class", ch);
      i += 1;
      continue;
    }

    let j = i + 1;
    while (j < source.length && !SPECIAL.includes(source[j])) j += 1;
    push("literal", source.slice(i, j));
    i = j;
  }
  return tokens;
}
