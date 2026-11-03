// ---------------------------------------------------------------------------
// Petacat -- Tests for the Training Mode Sessions problem-text parser
// ---------------------------------------------------------------------------
//
// What these defend: every accepted format yields the same problem, strings are
// any Unicode text and case-sensitive, duplicates are exact matches only, a line that
// cannot be read is reported with its number and a reason rather than dropped, and
// the repository's own problem list parses whole.
// ---------------------------------------------------------------------------

import { describe, it, expect } from 'vitest'

// The repository's own list, read as text at build time (no Node typings needed).
import problemListMd from '../../../../list-of-letter-string-analogy-problems.md?raw'
import { parseProblemText, chunk, formatProblem, fieldText, quoteField } from './problemText'

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

describe('parseProblemText: any text, case and limits', () => {
  it('accepts digits, punctuation and inner spaces in an unquoted arrow problem', () => {
    const r = parseProblemText('abc → ab1; xyz → ?\nabc → abd; x_z → ?\nabc → abd; xyz → w yz')
    expect(r.rejected).toEqual([])
    expect(r.problems.map((p) => [p.modified, p.target, p.answer])).toEqual([
      ['ab1', 'xyz', null],
      ['abd', 'x_z', null],
      ['abd', 'xyz', 'w yz'],
    ])
  })

  it('keeps case: abC is not abc', () => {
    const r = parseProblemText('abC → abd; xyz → ?\nabc → abd; xyz → ?')
    expect(r.problems).toHaveLength(2)
    expect(r.problems[0].initial).toBe('abC')
    expect(r.duplicates).toEqual([])
  })

  it('has no length limit', () => {
    const long = 'a'.repeat(1000)
    const r = parseProblemText(`${long} ${long} ${long}\n${long}b abd xyz`)
    expect(r.rejected).toEqual([])
    expect(r.problems).toHaveLength(2)
    expect(r.problems[0].initial).toHaveLength(1000)
  })

  it('rejects an empty string in an arrow problem', () => {
    const r = parseProblemText(' → abd; xyz → ?')
    expect(r.rejected[0].reason).toMatch(/initial is empty/)
  })

  it('rejects U+0000 and a lone surrogate, which the database cannot store', () => {
    const r = parseProblemText('"a\\u0000b" abd xyz\n"\\ud800" abd xyz\nabc abd xyz "x\\udc00"')
    expect(r.problems).toEqual([])
    expect(r.rejected[0].reason).toMatch(/U\+0000/)
    expect(r.rejected[1].reason).toMatch(/not valid Unicode/)
    expect(r.rejected[2].reason).toMatch(/answer is not valid Unicode/)
  })

  it('does not trim unquoted text that is already trimmed, and does not change NFC to NFD', () => {
    const nfc = '\u00e9'
    const nfd = 'e\u0301'
    const r = parseProblemText(`${nfc} ${nfd} xyz`)
    expect(r.problems[0].initial).toBe(nfc)
    expect(r.problems[0].modified).toBe(nfd)
    expect(r.problems[0].initial).not.toBe(r.problems[0].modified)
  })
})

describe('parseProblemText: quoting', () => {
  const corpus = [
    'a b', 'a,b;c', 'x->y', 'ABC', '1 2 3', '\u00e9', 'e\u0301', 'αβγ', 'абв', 'אבג', '漢字', 'नमस्ते',
    '😀', '👨‍👩‍👧', '🇨🇦', '\t', 'a\nb', '\ufeff', '\u202e', 'say "hi"', 'back`tick', '#hash', '//slash',
    '→', '?', '  padded  ', 'a'.repeat(1000), 'C:\\dir',
  ]
  const q = (s: string) => JSON.stringify(s)

  it('keeps every corpus string exactly in the arrow form', () => {
    for (const s of corpus) {
      const r = parseProblemText(`${q(s)} → ${q('m')}; ${q(s)} → ${q(s)}`)
      expect(r.rejected, s).toEqual([])
      expect(r.problems, s).toEqual([{ initial: s, modified: 'm', target: s, answer: s }])
    }
  })

  it('keeps every corpus string exactly with the ASCII arrow, whitespace and CSV forms', () => {
    for (const s of corpus) {
      const expected = [{ initial: s, modified: 'm', target: s, answer: null }]
      expect(parseProblemText(`${q(s)} -> m; ${q(s)}`).problems, s).toEqual(expected)
      expect(parseProblemText(`${q(s)} m ${q(s)}`).problems, s).toEqual(expected)
      expect(parseProblemText(`${q(s)},m,${q(s)}`).problems, s).toEqual(expected)
    }
  })

  it('keeps a quoted field in a backticked Markdown span, even one holding a backtick or arrow', () => {
    const r = parseProblemText('| `"a -> b" → "c`d"; "x; y" → ?` | note |')
    expect(r.rejected).toEqual([])
    expect(r.problems).toEqual([{ initial: 'a -> b', modified: 'c`d', target: 'x; y', answer: null }])
  })

  it('does not trim inside the quotes', () => {
    expect(parseProblemText('" a " → "b "; " c" → ?').problems).toEqual([
      { initial: ' a ', modified: 'b ', target: ' c', answer: null },
    ])
  })

  it('reads JSON escapes and a literal tab inside quotes', () => {
    const r = parseProblemText('"x\\ny" "\\u00e9\\t" "tab\there"')
    expect(r.problems).toEqual([{ initial: 'x\ny', modified: 'é\t', target: 'tab\there', answer: null }])
  })

  it('treats an unquoted ? as discovery and a quoted "?" as the string ?', () => {
    expect(parseProblemText('abc → abd; xyz → ?').problems[0].answer).toBeNull()
    expect(parseProblemText('abc abd xyz ?').problems[0].answer).toBeNull()
    expect(parseProblemText('abc → abd; xyz → "?"').problems[0].answer).toBe('?')
    expect(parseProblemText('abc abd xyz "?"').problems[0].answer).toBe('?')
    expect(parseProblemText('abc,abd,xyz,"?"').problems[0].answer).toBe('?')
  })

  it('rejects an empty quoted answer and an empty quoted field', () => {
    const r = parseProblemText('abc → abd; xyz → ""\n"" abd xyz')
    expect(r.rejected[0].reason).toMatch(/answer is empty/)
    expect(r.rejected[1].reason).toMatch(/initial is empty/)
  })

  it('reports an unterminated quote, an unknown escape and text glued to a quote', () => {
    const r = parseProblemText('"abc → abd; xyz → ?\n"a\\qb" abd xyz\n"abc"x abd xyz\nabc "ab"cd xyz')
    expect(r.problems).toEqual([])
    expect(r.rejected[0].reason).toMatch(/unterminated quote opened at column 1/)
    expect(r.rejected[1].reason).toMatch(/unknown escape/)
    expect(r.rejected[2].reason).toMatch(/directly after the closing quote/)
    expect(r.rejected[3].reason).toMatch(/directly after the closing quote/)
  })

  it('treats a quote that does not start a field as ordinary text', () => {
    expect(parseProblemText('ab"c abd xyz').problems[0].initial).toBe('ab"c')
    expect(parseProblemText('abc → a"b; xyz → ?').problems[0].modified).toBe('a"b')
  })

  it('does not drop a quoted problem that starts with # or contains an arrow lookalike', () => {
    const r = parseProblemText('"#a" "->" "//"')
    expect(r.problems).toEqual([{ initial: '#a', modified: '->', target: '//', answer: null }])
  })

  it('keeps the NFC and NFD forms distinct, and exact repeats are the only duplicates', () => {
    const r = parseProblemText('"é" b c\n"e\u0301" b c\n"é" b c')
    expect(r.problems).toHaveLength(2)
    expect(r.duplicates).toHaveLength(1)
  })

  it('quoteField and fieldText write fields that read back exactly', () => {
    for (const s of corpus) {
      const r = parseProblemText(`${fieldText(s)} → ${fieldText(s)}; ${fieldText(s)} → ${fieldText(s)}`)
      expect(r.problems, s).toEqual([{ initial: s, modified: s, target: s, answer: s }])
    }
    expect(fieldText('abC')).toBe('abC')
    expect(fieldText('?')).toBe('"?"')
    expect(quoteField('a b')).toBe('"a b"')
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
    const r = parseProblemText('| `1234 → 4321; "nopq → ?` | x |\n| `abc → abd; xyz → ?` | x |')
    expect(r.problems).toHaveLength(1)
    expect(r.rejected).toHaveLength(1)
    expect(r.rejected[0].line).toBe(1)
    expect(r.rejected[0].reason).toMatch(/unterminated quote/)
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
    // Every table row either gives a problem or is a reported duplicate; the list's one
    // non-letter problem (1234 → 4321) is now an ordinary problem too.
    expect(r.problems.length).toBeGreaterThan(150)
    expect(r.problems.length + r.duplicates.length + r.rejected.length).toBeGreaterThanOrEqual(rows.length)
    expect(r.problems.some((p) => p.initial === 'abc' && p.modified === 'abd' && p.target === 'xyz')).toBe(true)
    expect(r.rejected).toEqual([])
    expect(r.problems.some((p) => p.initial === '1234')).toBe(true)
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
        { initial: 'abc', modified: '', target: 'xyz' },
        { initial: 'abc', modified: 'abd' },
        'abc',
        { initial: 'abc', modified: 'abd', target: 'xyz', seeds: 0 },
      ]),
    )
    expect(r.problems).toEqual([{ ...ABC, seeds: 5, tag: { job: 7 } }])
    expect(r.rejected.map((x) => x.line)).toEqual([2, 3, 4, 5])
  })

  it('keeps JSON strings exactly: no trimming, "?" is the string ?, null is discovery', () => {
    const r = parseProblemText(
      JSON.stringify([
        { initial: ' a b ', modified: 'x\ny', target: '😀', answer: '?' },
        { initial: 'é', modified: 'e\u0301', target: 'x', answer: null },
        { initial: 'a'.repeat(1000), modified: 'b', target: 'c' },
      ]),
    )
    expect(r.rejected).toEqual([])
    expect(r.problems[0]).toEqual({ initial: ' a b ', modified: 'x\ny', target: '😀', answer: '?' })
    expect(r.problems[1].answer).toBeNull()
    expect(r.problems[2].initial).toHaveLength(1000)
  })

  it('rejects U+0000 in JSON strings', () => {
    const r = parseProblemText(JSON.stringify([{ initial: 'a\u0000', modified: 'b', target: 'c' }]))
    expect(r.rejected[0].reason).toMatch(/U\+0000/)
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
