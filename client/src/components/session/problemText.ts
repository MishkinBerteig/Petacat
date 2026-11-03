// ---------------------------------------------------------------------------
// Petacat -- Training Mode Sessions: turning pasted or uploaded text into problems
// ---------------------------------------------------------------------------
//
// A researcher has problems in a note, a spreadsheet, a JSON file or the repository's
// own list-of-letter-string-analogy-problems.md. This module reads any of them into
// `ProblemInput[]` and says, line by line, what it could not read and why, so the
// preview can show what will be sent before anything is.
//
// Pure: no DOM, no fetch. Any Unicode text is a valid problem string (any script, emoji,
// spaces, punctuation, any case, any length) and is kept exactly: no trimming of a
// quoted field's own content, no case change, no normalisation (abC is not abc; NFC and
// NFD spellings of one letter are two strings). Only what the database cannot store is
// refused: an empty string, U+0000, and a lone surrogate (not valid Unicode).
//
// Formats, one problem per line unless noted:
//   abc -> abd; xyz -> ?        (arrow may be -> or the character →)
//   abc -> abd; xyz -> wyz      justification: the answer to explain is wyz
//   abc abd xyz [answer]        whitespace separated
//   abc,abd,xyz[,answer]        CSV, optional header row
//   | `abc → abd; xyz → ?` | ... |   Markdown row: first backticked problem on the line
//   [{"initial": ...}, ...]     JSON array, when the whole text is JSON
// Blank lines and lines starting with # or // are ignored.
//
// Quoting, in every line form: a field may be written in double quotes with JSON string
// syntax -- "a b", "a,b", "x\ny", "say \"hi\"", "\u00e9" -- and is then kept exactly
// (no trimming inside the quotes). Separators (; -> → , whitespace, backticks) inside
// quotes do not split. A quote opens a quoted field only at the start of a field (after
// whitespace, a separator or the start of the line); a quote anywhere else is ordinary
// text. An unquoted answer ? means discovery; the quoted answer "?" is the string ?.
// Unquoted fields are trimmed, as they always were.
// ---------------------------------------------------------------------------

import type { ProblemInput } from '@/types';

export interface RejectedLine {
  /** 1-based line number (for JSON, the 1-based position in the array). */
  line: number;
  text: string;
  reason: string;
}

export interface ParsedProblems {
  problems: ProblemInput[];
  rejected: RejectedLine[];
  /** Exact repeats of an earlier problem in the same text; not in `problems`. */
  duplicates: RejectedLine[];
}

const ARROW = /→|->/;
/** A lone high or low surrogate: not valid Unicode, cannot be stored as UTF-8. */
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

type Fields = { initial: string; modified: string; target: string; answer: string | null };
type Outcome = { ok: true; value: Fields } | { ok: false; reason: string };
/** One field as read: its value, and whether it was written in quotes. */
type Field = { v: string; quoted: boolean };
/** A piece of a line: a decoded quoted field (`q`), or raw unquoted text. */
type Tok = { q: boolean; v: string };

function fail(reason: string): Outcome {
  return { ok: false, reason };
}

/** Quote a field so that this parser reads it back exactly (JSON string syntax). */
export function quoteField(s: string): string {
  return JSON.stringify(s);
}

/**
 * A field as it can be written in a line: bare when that reads back exactly (letters,
 * marks and digits only, and not the discovery marker), otherwise quoted.
 */
export function fieldText(s: string): string {
  return /^[\p{L}\p{M}\p{N}]+$/u.test(s) ? s : quoteField(s);
}

function checkString(role: string, s: string): string | null {
  if (s === '') return `${role} is empty`;
  if (s.includes('\u0000')) {
    return `${role} contains the character U+0000 (NUL), which the database cannot store`;
  }
  if (LONE_SURROGATE.test(s)) {
    return `${role} is not valid Unicode text (it contains a lone surrogate)`;
  }
  return null;
}

/** Validate the four strings. `answer` null means discovery; any string is kept exactly. */
function finish(initial: string, modified: string, target: string, answer: string | null): Outcome {
  const checks: [string, string][] = [
    ['initial', initial],
    ['modified', modified],
    ['target', target],
  ];
  if (answer !== null) checks.push(['answer', answer]);
  for (const [role, s] of checks) {
    const bad = checkString(role, s);
    if (bad) return fail(bad);
  }
  return { ok: true, value: { initial, modified, target, answer } };
}

/** The line forms' answer: an unquoted '' or '?' is discovery, a quoted field is literal. */
function answerOf(f: Field | null): string | null {
  if (f === null) return null;
  if (f.quoted) return f.v;
  return f.v === '' || f.v === '?' ? null : f.v;
}

function build(initial: Field, modified: Field, target: Field, answer: Field | null): Outcome {
  return finish(initial.v, modified.v, target.v, answerOf(answer));
}

const ESCAPES: Record<string, string> = {
  '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t',
};

/** Characters after which a quote opens a quoted field. */
function opensQuote(prev: string | undefined): boolean {
  return prev === undefined || /\s/.test(prev) || ';,>→`|'.includes(prev);
}

/**
 * Cut a line into quoted fields (decoded) and the raw text between them, so that
 * separators are only looked for outside quotes. Inside quotes a backslash escape is JSON's
 * (\" \\ \/ \b \f \n \r \t \uXXXX); any other character, a tab included, is kept as typed.
 */
function tokenize(line: string): { ok: true; toks: Tok[] } | { ok: false; reason: string } {
  const toks: Tok[] = [];
  let raw = '';
  let i = 0;
  while (i < line.length) {
    const c = line[i];
    if (c !== '"' || !opensQuote(line[i - 1])) {
      raw += c;
      i += 1;
      continue;
    }
    const open = i;
    let v = '';
    let j = i + 1;
    let closed = false;
    while (j < line.length) {
      const d = line[j];
      if (d === '"') {
        closed = true;
        break;
      }
      if (d === '\\') {
        const e = line[j + 1];
        if (e === 'u') {
          const hex = line.slice(j + 2, j + 6);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
            return { ok: false, reason: `bad \\u escape in the quotes at column ${j + 1}` };
          }
          v += String.fromCharCode(parseInt(hex, 16));
          j += 6;
          continue;
        }
        if (e === undefined || !(e in ESCAPES)) {
          return {
            ok: false,
            reason: `unknown escape \\${e ?? ''} in the quotes at column ${j + 1} (write \\\\ for a backslash)`,
          };
        }
        v += ESCAPES[e];
        j += 2;
        continue;
      }
      v += d;
      j += 1;
    }
    if (!closed) return { ok: false, reason: `unterminated quote opened at column ${open + 1}` };
    const next = line[j + 1];
    if (next !== undefined && !/\s/.test(next) && !';,-→|`'.includes(next)) {
      return {
        ok: false,
        reason: `text directly after the closing quote at column ${j + 1}; separate fields with a space, comma, semicolon or arrow`,
      };
    }
    if (raw !== '') toks.push({ q: false, v: raw });
    raw = '';
    toks.push({ q: true, v });
    i = j + 1;
  }
  if (raw !== '') toks.push({ q: false, v: raw });
  return { ok: true, toks };
}

/** Split tokens at `sep`, looked for in unquoted text only; a quoted token never splits. */
function splitToks(toks: Tok[], sep: RegExp): Tok[][] {
  const out: Tok[][] = [];
  let cur: Tok[] = [];
  for (const t of toks) {
    if (t.q) {
      cur.push(t);
      continue;
    }
    t.v.split(sep).forEach((piece, k) => {
      if (k > 0) {
        out.push(cur);
        cur = [];
      }
      if (piece !== '') cur.push({ q: false, v: piece });
    });
  }
  out.push(cur);
  return out;
}

/** One field's tokens as a value: a lone quoted field exactly, or the unquoted text trimmed. */
function readField(parts: Tok[]): Field | string {
  const quoted = parts.filter((t) => t.q);
  if (quoted.length === 0) return { v: parts.map((t) => t.v).join('').trim(), quoted: false };
  const others = parts.filter((t) => !t.q).map((t) => t.v).join('').trim();
  if (quoted.length > 1 || others !== '') {
    return 'a quoted field cannot be joined with other text; put the whole field in one pair of quotes';
  }
  return { v: quoted[0].v, quoted: true };
}

function readFields(groups: Tok[][]): Field[] | string {
  const fields: Field[] = [];
  for (const g of groups) {
    const f = readField(g);
    if (typeof f === 'string') return f;
    fields.push(f);
  }
  return fields;
}

const hasUnquoted = (toks: Tok[], re: RegExp) => toks.some((t) => !t.q && re.test(t.v));

/** `abc -> abd; xyz -> ?`, `abc → abd; xyz → wyz`, `abc -> abd; xyz`, with fields optionally quoted. */
function parseArrowToks(toks: Tok[]): Outcome {
  const halves = splitToks(toks, /;/);
  if (halves.length !== 2) {
    return fail('expected "initial → modified; target → ?" with one semicolon (outside quotes)');
  }
  const top = readFields(splitToks(halves[0], ARROW));
  if (typeof top === 'string') return fail(top);
  if (top.length !== 2) return fail('expected "initial → modified" before the semicolon');
  const bottom = readFields(splitToks(halves[1], ARROW));
  if (typeof bottom === 'string') return fail(bottom);
  if (bottom.length > 2) return fail('expected "target → ?" after the semicolon');
  return build(top[0], top[1], bottom[0], bottom.length === 2 ? bottom[1] : null);
}

/** `abc -> abd; xyz -> ?` as one string (a backticked span, or a whole line). */
export function parseArrowForm(text: string): Outcome {
  const t = tokenize(text);
  return t.ok ? parseArrowToks(t.toks) : fail(t.reason);
}

function parseFieldList(fields: Field[]): Outcome {
  if (fields.length < 3 || fields.length > 4) {
    return fail(`expected 3 or 4 fields (initial modified target [answer]), found ${fields.length}`);
  }
  return build(fields[0], fields[1], fields[2], fields.length === 4 ? fields[3] : null);
}

function isHeader(fields: Field[]): boolean {
  if (fields.some((f) => f.quoted)) return false;
  const lower = fields.map((f) => f.v.toLowerCase());
  return lower.includes('initial') && lower.includes('modified') && lower.includes('target');
}

function looksLikeProblem(toks: Tok[]): boolean {
  return hasUnquoted(toks, ARROW) || hasUnquoted(toks, /;/);
}

/**
 * The first backticked problem in a line. `whole` is the line's tokens when the line reads
 * whole (so a backtick inside quotes is not a delimiter); when it does not (prose outside
 * the backticks may hold a stray quote) each backticked span is read on its own.
 */
function parseBacktickLine(line: string, whole: Tok[] | null): Outcome | null {
  let spans: Tok[][];
  if (whole) {
    // Odd-numbered groups lie between a pair of backticks; a last, unclosed one is not a span.
    spans = splitToks(whole, /`/).filter((_, i, all) => i % 2 === 1 && i < all.length - 1);
  } else {
    spans = [];
    for (const m of line.matchAll(/`([^`]+)`/g)) {
      const t = tokenize(m[1]);
      if (!t.ok) return fail(t.reason);
      spans.push(t.toks);
    }
  }
  let firstFailure: Outcome | null = null;
  for (const span of spans) {
    if (span.length === 0 || !looksLikeProblem(span)) continue;
    const out = parseArrowToks(span);
    if (out.ok) return out;
    firstFailure ??= out;
  }
  return firstFailure; // null when no backticked span even looked like a problem
}

/**
 * One line of text. Returns a problem, a rejection, or `null` when the line is to be
 * ignored (blank, a comment, a table's header or rule, prose with no problem in it).
 */
function parseLine(raw: string, markdown: boolean): Outcome | null {
  const line = raw.trim();
  if (line === '' || line.startsWith('#') || line.startsWith('//')) return null;

  const t = tokenize(line);
  if (line.includes('`') && (!t.ok || hasUnquoted(t.toks, /`/))) {
    return parseBacktickLine(line, t.ok ? t.toks : null);
  }

  if (line.startsWith('|')) return null; // a table header or rule with no problem in it

  // In a Markdown document the prose lines are not malformed problems.
  if (!t.ok) return markdown ? null : fail(t.reason);

  if (hasUnquoted(t.toks, ARROW)) return parseArrowToks(t.toks);

  if (markdown) return null;

  if (hasUnquoted(t.toks, /,/)) {
    const fields = readFields(splitToks(t.toks, /,/));
    if (typeof fields === 'string') return fail(fields);
    if (isHeader(fields)) return null;
    return parseFieldList(fields);
  }

  const groups = splitToks(t.toks, /\s+/).filter((g) => g.length > 0);
  const fields = readFields(groups);
  if (typeof fields === 'string') return fail(fields);
  if (isHeader(fields)) return null;
  return parseFieldList(fields);
}

function keyOf(p: Fields): string {
  return JSON.stringify([p.initial, p.modified, p.target, p.answer]);
}

function parseJson(value: unknown): ParsedProblems {
  const result: ParsedProblems = { problems: [], rejected: [], duplicates: [] };
  const items = Array.isArray(value) ? value : [value];
  const seen = new Set<string>();
  items.forEach((item, i) => {
    const text = JSON.stringify(item) ?? String(item);
    const where = { line: i + 1, text: text.length > 200 ? `${text.slice(0, 200)}…` : text };
    if (item === null || typeof item !== 'object' || Array.isArray(item)) {
      result.rejected.push({ ...where, reason: 'expected an object {initial, modified, target, answer?}' });
      return;
    }
    const o = item as Record<string, unknown>;
    for (const k of ['initial', 'modified', 'target']) {
      if (typeof o[k] !== 'string') {
        result.rejected.push({ ...where, reason: `"${k}" is missing or not a string` });
        return;
      }
    }
    if (o.answer !== undefined && o.answer !== null && typeof o.answer !== 'string') {
      result.rejected.push({ ...where, reason: '"answer" is not a string' });
      return;
    }
    // Kept exactly as the JSON gives them. A null or absent answer (or an empty one) is
    // discovery; any other string, "?" included, is the answer.
    const ans = (o.answer as string | null | undefined) ?? null;
    const out = finish(o.initial as string, o.modified as string, o.target as string, ans === '' ? null : ans);
    if (!out.ok) {
      result.rejected.push({ ...where, reason: out.reason });
      return;
    }
    if (o.seeds !== undefined && o.seeds !== null) {
      if (typeof o.seeds !== 'number' || !Number.isInteger(o.seeds) || o.seeds < 1) {
        result.rejected.push({ ...where, reason: '"seeds" is not a positive whole number' });
        return;
      }
    }
    const key = keyOf(out.value);
    if (seen.has(key)) {
      result.duplicates.push({ ...where, reason: 'duplicate of an earlier problem' });
      return;
    }
    seen.add(key);
    const problem: ProblemInput = { ...out.value };
    if (typeof o.seeds === 'number') problem.seeds = o.seeds;
    if (o.tag !== undefined) problem.tag = o.tag;
    result.problems.push(problem);
  });
  return result;
}

/** Read problems from pasted or uploaded text. Never throws. */
export function parseProblemText(text: string): ParsedProblems {
  const trimmed = text.trim();
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    try {
      return parseJson(JSON.parse(trimmed));
    } catch {
      // Not JSON after all (a Markdown link list, say): read it line by line.
    }
  }

  const result: ParsedProblems = { problems: [], rejected: [], duplicates: [] };
  const seen = new Set<string>();
  const lines = text.split(/\r\n|\r|\n/);
  // A table row holding a backticked problem marks the text as Markdown.
  const markdown = lines.some((l) => /^\s*\|.*`[^`]*(→|->)[^`]*`/.test(l));
  lines.forEach((raw, i) => {
    const out = parseLine(raw, markdown);
    if (out === null) return;
    const shown = raw.trim().length > 200 ? `${raw.trim().slice(0, 200)}…` : raw.trim();
    const where = { line: i + 1, text: shown };
    if (!out.ok) {
      result.rejected.push({ ...where, reason: out.reason });
      return;
    }
    const key = keyOf(out.value);
    if (seen.has(key)) {
      result.duplicates.push({ ...where, reason: 'duplicate of an earlier problem' });
      return;
    }
    seen.add(key);
    result.problems.push({ ...out.value });
  });
  return result;
}

/** `abc → abd; xyz` -- the answer, for a justification problem, is shown separately. */
export function formatProblem(p: { initial: string; modified: string; target: string }): string {
  return `${p.initial} → ${p.modified}; ${p.target}`;
}

/** Split into requests of at most `size` problems (at least one request, possibly empty). */
export function chunk<T>(items: T[], size: number): T[][] {
  const n = Math.max(1, Math.floor(size));
  if (items.length === 0) return [[]];
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += n) out.push(items.slice(i, i + n));
  return out;
}
