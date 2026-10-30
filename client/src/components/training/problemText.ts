// ---------------------------------------------------------------------------
// Petacat -- Trainings: turning pasted or uploaded text into problems
// ---------------------------------------------------------------------------
//
// A researcher has problems in a note, a spreadsheet, a JSON file or the repository's
// own list-of-letter-string-analogy-problems.md. This module reads any of them into
// `ProblemInput[]` and says, line by line, what it could not read and why, so the
// preview can show what will be sent before anything is.
//
// Pure: no DOM, no fetch. Strings are letters only and case-sensitive (abC is not abc).
//
// Formats, one problem per line unless noted:
//   abc -> abd; xyz -> ?        (arrow may be -> or the character →)
//   abc -> abd; xyz -> wyz      justification: the answer to explain is wyz
//   abc abd xyz [answer]        whitespace separated
//   abc,abd,xyz[,answer]        CSV, optional header row
//   | `abc → abd; xyz → ?` | ... |   Markdown row: first backticked problem on the line
//   [{"initial": ...}, ...]     JSON array, when the whole text is JSON
// Blank lines and lines starting with # or // are ignored.
// ---------------------------------------------------------------------------

import type { ProblemInput } from '@/types';

export const MAX_STRING_LENGTH = 64;

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

const LETTERS = /^[A-Za-z]+$/;
const ARROW = /→|->/;

type Fields = { initial: string; modified: string; target: string; answer: string | null };
type Outcome = { ok: true; value: Fields } | { ok: false; reason: string };

function fail(reason: string): Outcome {
  return { ok: false, reason };
}

function checkString(role: string, s: string): string | null {
  if (s === '') return `${role} is empty`;
  if (!LETTERS.test(s)) return `${role} "${s}" is not letters only`;
  if (s.length > MAX_STRING_LENGTH) return `${role} is longer than ${MAX_STRING_LENGTH} letters`;
  return null;
}

/** Validate the four strings; an answer of '' or '?' means discovery. */
function build(initial: string, modified: string, target: string, answer: string | null): Outcome {
  const checks: [string, string][] = [
    ['initial', initial],
    ['modified', modified],
    ['target', target],
  ];
  for (const [role, s] of checks) {
    const bad = checkString(role, s);
    if (bad) return fail(bad);
  }
  let ans: string | null = answer === null ? null : answer.trim();
  if (ans === '' || ans === '?') ans = null;
  if (ans !== null) {
    const bad = checkString('answer', ans);
    if (bad) return fail(bad);
  }
  return { ok: true, value: { initial, modified, target, answer: ans } };
}

/** `abc -> abd; xyz -> ?`, `abc → abd; xyz → wyz`, `abc -> abd; xyz`. */
export function parseArrowForm(text: string): Outcome {
  const halves = text.split(';');
  if (halves.length !== 2) {
    return fail('expected "initial → modified; target → ?" with one semicolon');
  }
  const top = halves[0].split(ARROW).map((s) => s.trim());
  if (top.length !== 2) return fail('expected "initial → modified" before the semicolon');
  const bottom = halves[1].split(ARROW).map((s) => s.trim());
  if (bottom.length > 2) return fail('expected "target → ?" after the semicolon');
  return build(top[0], top[1], bottom[0], bottom.length === 2 ? bottom[1] : null);
}

function parseFieldList(fields: string[]): Outcome {
  if (fields.length < 3 || fields.length > 4) {
    return fail(`expected 3 or 4 fields (initial modified target [answer]), found ${fields.length}`);
  }
  return build(fields[0], fields[1], fields[2], fields.length === 4 ? fields[3] : null);
}

function unquote(s: string): string {
  const t = s.trim();
  return t.length >= 2 && t.startsWith('"') && t.endsWith('"') ? t.slice(1, -1).trim() : t;
}

function isHeader(fields: string[]): boolean {
  const lower = fields.map((f) => f.toLowerCase());
  return lower.includes('initial') && lower.includes('modified') && lower.includes('target');
}

function looksLikeProblem(span: string): boolean {
  return ARROW.test(span) || span.includes(';');
}

/**
 * One line of text. Returns a problem, a rejection, or `null` when the line is to be
 * ignored (blank, a comment, a table's header or rule, prose with no problem in it).
 */
function parseLine(raw: string, markdown: boolean): Outcome | null {
  const line = raw.trim();
  if (line === '' || line.startsWith('#') || line.startsWith('//')) return null;

  if (line.includes('`')) {
    const spans = [...line.matchAll(/`([^`]+)`/g)].map((m) => m[1].trim());
    let firstFailure: Outcome | null = null;
    for (const span of spans) {
      if (!looksLikeProblem(span)) continue;
      const out = parseArrowForm(span);
      if (out.ok) return out;
      firstFailure ??= out;
    }
    return firstFailure; // null when no backticked span even looked like a problem
  }

  if (line.startsWith('|')) return null; // a table header or rule with no problem in it

  if (ARROW.test(line)) return parseArrowForm(line);

  // In a Markdown document the remaining lines are prose, not malformed problems.
  if (markdown) return null;

  if (line.includes(',')) {
    const fields = line.split(',').map(unquote);
    if (isHeader(fields)) return null;
    return parseFieldList(fields);
  }

  const fields = line.split(/\s+/);
  if (isHeader(fields)) return null;
  return parseFieldList(fields);
}

function keyOf(p: Fields): string {
  return `${p.initial}\u0000${p.modified}\u0000${p.target}\u0000${p.answer ?? ''}`;
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
    const out = build(
      (o.initial as string).trim(),
      (o.modified as string).trim(),
      (o.target as string).trim(),
      (o.answer as string | null | undefined) ?? null,
    );
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
