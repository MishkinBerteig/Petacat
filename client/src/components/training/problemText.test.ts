// ---------------------------------------------------------------------------
// Petacat -- Tests for the Trainings problem-text parser
// ---------------------------------------------------------------------------
//
// What these defend: every accepted format yields the same problem, strings are
// letters only and case-sensitive, duplicates are exact matches only, a line that
// cannot be read is reported with its number and a reason rather than dropped, and
// the repository's own problem list parses whole.
// ---------------------------------------------------------------------------

import { describe, it, expect } from 'vitest'

// The repository's own list, read as text at build time (no Node typings needed).
import problemListMd from '../../../../list-of-letter-string-analogy-problems.md?raw'
import { parseProblemText, chunk, formatProblem } from './problemText'

const ABC = { initial: 'abc', modified: 'abd', target: 'xyz', answer: null }

describe('parseProblemText: arrow form', () => {
  it('reads a discovery problem with the unicode arrow', () => {
    const r = parseProblemText('abc → abd; xyz → ?')
    expect(r.problems).toEqual([ABC])
    expect(r.rejected).toEqual([])
  })

  it('reads the ASCII arrow', () => {
    expect(parseProblemText('abc -> abd; xyz -> ?').problems).toEqual([ABC])
  })

  it('treats no trailing part, and a bare trailing arrow, as discovery', () => {
    expect(parseProblemText('abc → abd; xyz').problems).toEqual([ABC])
    expect(parseProblemText('abc → abd; xyz →').problems).toEqual([ABC])
  })

  it('reads justification mode', () => {
    const r = parseProblemText('abc → abd; xyz → wyz')
    expect(r.problems).toEqual([{ ...ABC, answer: 'wyz' }])
  })

  it('tolerates uneven spacing and CRLF line endings', () => {
    const r = parseProblemText('  abc->abd ;xyz->?  \r\nabc → abd ;  xyz → wyz\r\n')
    expect(r.problems).toHaveLength(2)
    expect(r.rejected).toEqual([])
  })

  it('rejects a missing semicolon, with the line number', () => {
    const r = parseProblemText('abc → abd; xyz → ?\nabc → abd')
    expect(r.problems).toHaveLength(1)
    expect(r.rejected).toHaveLength(1)
    expect(r.rejected[0].line).toBe(2)
    expect(r.rejected[0].reason).toMatch(/semicolon/)
  })

  it('rejects an extra arrow', () => {
    const r = parseProblemText('abc → abd → abe; xyz → ?')
    expect(r.problems).toEqual([])
    expect(r.rejected).toHaveLength(1)
  })
})

describe('parseProblemText: whitespace and CSV', () => {
  it('reads whitespace separated strings, with and without an answer', () => {
    const r = parseProblemText('abc abd xyz\nabc\tabd\txyz\twyz')
    expect(r.problems).toEqual([ABC, { ...ABC, answer: 'wyz' }])
  })

  it('reads a ? in the fourth place as discovery', () => {
    expect(parseProblemText('abc abd xyz ?').problems).toEqual([ABC])
  })

  it('reads CSV with and without an answer', () => {
    const r = parseProblemText('abc,abd,xyz\nabc, abd, xyz, wyz')
    expect(r.problems).toEqual([ABC, { ...ABC, answer: 'wyz' }])
  })

  it('reads a CSV with an empty fourth field as discovery', () => {
    expect(parseProblemText('abc,abd,xyz,').problems).toEqual([ABC])
  })

  it('skips a CSV header row (any case)', () => {
    const r = parseProblemText('Initial,Modified,Target,Answer\nabc,abd,xyz,')
    expect(r.problems).toEqual([ABC])
    expect(r.rejected).toEqual([])
  })

  it('skips a whitespace header row', () => {
    const r = parseProblemText('initial modified target answer\nabc abd xyz')
    expect(r.problems).toEqual([ABC])
    expect(r.rejected).toEqual([])
  })

  it('reads quoted CSV fields', () => {
    expect(parseProblemText('"abc","abd","xyz"').problems).toEqual([ABC])
  })

  it('rejects the wrong number of fields', () => {
    const r = parseProblemText('abc abd\nabc abd xyz wyz extra\na,b')
    expect(r.problems).toEqual([])
    expect(r.rejected.map((x) => x.line)).toEqual([1, 2, 3])
    expect(r.rejected[0].reason).toMatch(/3 or 4 fields/)
  })
})

describe('parseProblemText: letters, case and limits', () => {
  it('rejects digits and punctuation, naming the field', () => {
    const r = parseProblemText('abc → ab1; xyz → ?\nabc → abd; x-z → ?\nabc → abd; xyz → w yz')
    expect(r.problems).toEqual([])
    expect(r.rejected[0].reason).toMatch(/modified "ab1" is not letters only/)
    expect(r.rejected[1].reason).toMatch(/target/)
    expect(r.rejected).toHaveLength(3)
  })

  it('keeps case: abC is not abc', () => {
    const r = parseProblemText('abC → abd; xyz → ?\nabc → abd; xyz → ?')
    expect(r.problems).toHaveLength(2)
    expect(r.problems[0].initial).toBe('abC')
    expect(r.duplicates).toEqual([])
  })

  it('rejects a string longer than 64 letters but accepts exactly 64', () => {
    const ok = 'a'.repeat(64)
    const bad = 'a'.repeat(65)
    const r = parseProblemText(`${ok} ${ok} ${ok}\n${bad} abd xyz`)
    expect(r.problems).toHaveLength(1)
    expect(r.rejected[0].line).toBe(2)
    expect(r.rejected[0].reason).toMatch(/64/)
  })

  it('rejects an empty string in an arrow problem', () => {
    const r = parseProblemText(' → abd; xyz → ?')
    expect(r.rejected[0].reason).toMatch(/initial is empty/)
  })

  it('rejects a non-letter answer', () => {
    const r = parseProblemText('abc → abd; xyz → w1z')
    expect(r.rejected[0].reason).toMatch(/answer/)
  })
})

describe('parseProblemText: ignored lines', () => {
  it('ignores blank lines and # and // comments', () => {
    const r = parseProblemText('# a heading\n\n   \n// note\nabc → abd; xyz → ?\n  # indented comment')
    expect(r.problems).toEqual([ABC])
    expect(r.rejected).toEqual([])
  })

  it('returns nothing for empty text', () => {
    expect(parseProblemText('')).toEqual({ problems: [], rejected: [], duplicates: [] })
  })
})

describe('parseProblemText: duplicates', () => {
  it('drops exact repeats and reports them with their line', () => {
    const r = parseProblemText('abc → abd; xyz → ?\nabc abd xyz\nabc,abd,xyz\nabc -> abd; xyz')
    expect(r.problems).toHaveLength(1)
    expect(r.duplicates.map((d) => d.line)).toEqual([2, 3, 4])
  })

  it('treats a different answer as a different problem', () => {
    const r = parseProblemText('abc → abd; xyz → ?\nabc → abd; xyz → wyz\nabc → abd; xyz → wyz')
    expect(r.problems).toHaveLength(2)
    expect(r.duplicates).toHaveLength(1)
  })
})

describe('parseProblemText: Markdown', () => {
  it('takes the first backticked problem on a table row', () => {
    const r = parseProblemText(
      '| Problem | Answer |\n|---|---|\n| `abc → abd; xyz → ?` | `xyd` 36.8% |\n| `rst → rsu; xyz → ?` | `xyu` |',
    )
    expect(r.problems.map(formatProblem)).toEqual(['abc → abd; xyz', 'rst → rsu; xyz'])
    expect(r.rejected).toEqual([])
  })

  it('ignores backticked words that are not problems', () => {
    const r = parseProblemText('See `demos.ss` and `copy1`.\n| `abc → abd; xyz → ?` | x |')
    expect(r.problems).toHaveLength(1)
    expect(r.rejected).toEqual([])
  })

  it('reports a backticked problem that cannot be read', () => {
    const r = parseProblemText('| `1234 → 4321; nopq → ?` | x |\n| `abc → abd; xyz → ?` | x |')
    expect(r.problems).toHaveLength(1)
    expect(r.rejected).toHaveLength(1)
    expect(r.rejected[0].line).toBe(1)
    expect(r.rejected[0].reason).toMatch(/not letters only/)
  })

  it('does not reject plain prose in a Markdown text', () => {
    const r = parseProblemText('Some prose here that is long.\n| `abc → abd; xyz → ?` | x |\nMore prose.')
    expect(r.problems).toHaveLength(1)
    expect(r.rejected).toEqual([])
  })

  it('skips the first problem span when a later one parses', () => {
    const r = parseProblemText('| `bad; 1` | `abc → abd; xyz → ?` |')
    expect(r.problems).toEqual([ABC])
  })

  it('parses the repository problem list whole', () => {
    const text: string = problemListMd
    const rows = text.split('\n').filter((l: string) => /^\| `[^`]*→[^`]*`/.test(l))
    expect(rows.length).toBeGreaterThan(150)
    const r = parseProblemText(text)
    // Every table row either gives a problem, is a reported duplicate, or is rejected
    // for a stated reason (the list holds one non-letter problem on purpose).
    expect(r.problems.length).toBeGreaterThan(150)
    expect(r.problems.length + r.duplicates.length + r.rejected.length).toBeGreaterThanOrEqual(rows.length)
    expect(r.problems.some((p) => p.initial === 'abc' && p.modified === 'abd' && p.target === 'xyz')).toBe(true)
    expect(r.rejected.some((x) => /1234/.test(x.text))).toBe(true)
    for (const p of r.problems) expect(p.initial).toMatch(/^[A-Za-z]+$/)
  })
})

describe('parseProblemText: JSON', () => {
  it('reads an array of objects', () => {
    const r = parseProblemText(
      JSON.stringify([
        { initial: 'abc', modified: 'abd', target: 'xyz' },
        { initial: 'abc', modified: 'abd', target: 'xyz', answer: 'wyz' },
        { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
      ]),
    )
    expect(r.problems).toEqual([
      ABC,
      { ...ABC, answer: 'wyz' },
      { initial: 'abc', modified: 'abd', target: 'ijk', answer: null },
    ])
  })

  it('keeps seeds and tag, and reports bad entries by position', () => {
    const r = parseProblemText(
      JSON.stringify([
        { initial: 'abc', modified: 'abd', target: 'xyz', seeds: 5, tag: { job: 7 } },
        { initial: 'abc', modified: 'ab1', target: 'xyz' },
        { initial: 'abc', modified: 'abd' },
        'abc',
        { initial: 'abc', modified: 'abd', target: 'xyz', seeds: 0 },
      ]),
    )
    expect(r.problems).toEqual([{ ...ABC, seeds: 5, tag: { job: 7 } }])
    expect(r.rejected.map((x) => x.line)).toEqual([2, 3, 4, 5])
  })

  it('drops duplicates within the array', () => {
    const o = { initial: 'abc', modified: 'abd', target: 'xyz' }
    const r = parseProblemText(JSON.stringify([o, o]))
    expect(r.problems).toHaveLength(1)
    expect(r.duplicates).toHaveLength(1)
  })

  it('accepts a single object', () => {
    expect(parseProblemText('{"initial":"abc","modified":"abd","target":"xyz"}').problems).toEqual([ABC])
  })

  it('falls back to lines when the text only starts like JSON', () => {
    const r = parseProblemText('[not json]\nabc abd xyz')
    expect(r.problems).toEqual([ABC])
    expect(r.rejected).toHaveLength(1)
  })
})

describe('helpers', () => {
  it('formatProblem writes the problem without its answer', () => {
    expect(formatProblem(ABC)).toBe('abc → abd; xyz')
  })

  it('chunk splits into requests of at most the size, and never returns none', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
    expect(chunk([1, 2], 5)).toEqual([[1, 2]])
    expect(chunk([], 5)).toEqual([[]])
    expect(chunk([1, 2, 3], 0)).toEqual([[1], [2], [3]])
  })
})
