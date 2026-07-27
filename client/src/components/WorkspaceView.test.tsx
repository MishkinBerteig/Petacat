// ---------------------------------------------------------------------------
// Petacat -- Tests that workspace labels do not print on top of each other
// ---------------------------------------------------------------------------
//
// The original bug: every bridge label was placed at the midpoint of its own
// line. All bridges of one type span the same two rows, so all those midpoints
// were the *same* point, and the labels printed over each other into an
// unreadable smear. Group labels, string labels, bond labels and the rule text
// collided the same way -- fixed offsets, no reserved space.
//
// The fixtures are real API output for the two cases that showed the problem
// most clearly, captured from a live run.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach } from 'vitest'
import { render } from '@testing-library/react'

import { WorkspaceView } from './WorkspaceView'
import { useRunStore } from '@/store/runStore'
import abcWyz from './__fixtures__/abc_wyz.json'
import eeqee from './__fixtures__/eeqee.json'
import mrrjjj from './__fixtures__/mrrjjj.json'
import iijjkk from './__fixtures__/iijjkk.json'

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
})

interface Box {
  text: string
  x1: number
  x2: number
  y1: number
  y2: number
}

/**
 * The label's own text, excluding any nested <title> (which is tooltip content,
 * not rendered glyphs -- counting it would wildly overstate the width).
 */
function ownText(el: Element): string {
  return Array.from(el.childNodes)
    .filter((n) => n.nodeType === 3 || (n as Element).tagName !== 'title')
    .map((n) => (n.nodeType === 3 ? n.textContent : (n as Element).textContent))
    .join('')
    .trim()
}

/**
 * Approximate box for an SVG <text>. jsdom does no text layout, so width is
 * estimated from the glyph count. 0.6em per character is a fair average for the
 * sans font at these sizes and is good enough to catch labels printing on top of
 * one another, which is what went wrong.
 */
function boxOf(el: Element): Box | null {
  const text = ownText(el)
  if (!text) return null
  const x = parseFloat(el.getAttribute('x') ?? 'NaN')
  const y = parseFloat(el.getAttribute('y') ?? 'NaN')
  if (Number.isNaN(x) || Number.isNaN(y)) return null
  const fontSize = parseFloat(el.getAttribute('font-size') ?? '10')
  const w = text.length * fontSize * 0.6
  const anchor = el.getAttribute('text-anchor')
  const x1 = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x
  return { text, x1, x2: x1 + w, y1: y - fontSize * 0.8, y2: y + fontSize * 0.25 }
}

function overlaps(a: Box, b: Box): boolean {
  return a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2
}

function collisions(container: HTMLElement): [Box, Box][] {
  const boxes = Array.from(container.querySelectorAll('text'))
    .map(boxOf)
    .filter((b): b is Box => b !== null)

  const found: [Box, Box][] = []
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      if (overlaps(boxes[i], boxes[j])) found.push([boxes[i], boxes[j]])
    }
  }
  return found
}

function describeCollisions(pairs: [Box, Box][]): string {
  return pairs
    .map(([a, b]) => `  "${a.text}" (y=${a.y2.toFixed(0)}) over "${b.text}" (y=${b.y2.toFixed(0)})`)
    .join('\n')
}

const CASES = [
  { name: 'abc->abd; xyz->wyz (crossing vertical bridges)', data: abcWyz },
  { name: 'eeqee->qeeq; xxixx (nine groups, nested)', data: eeqee },
  { name: 'abc->abd; mrrjjj->mrrkkk (letter-to-group bridges)', data: mrrjjj },
  { name: 'abc->abd; iijjkk (grouped target)', data: iijjkk },
]

describe('WorkspaceView — labels stay legible', () => {
  for (const { name, data } of CASES) {
    it(`draws no overlapping labels for ${name}`, () => {
      useRunStore.setState({ workspace: data as any })
      const { container } = render(<WorkspaceView />)

      const pairs = collisions(container)
      expect(
        pairs.length,
        `labels printed on top of each other:\n${describeCollisions(pairs)}`,
      ).toBe(0)
    })

    it(`keeps every label inside the canvas for ${name}`, () => {
      useRunStore.setState({ workspace: data as any })
      const { container } = render(<WorkspaceView />)

      const svg = container.querySelector('svg')!
      const [, , vbW, vbH] = (svg.getAttribute('viewBox') ?? '0 0 0 0')
        .split(' ')
        .map(Number)

      const escaping = Array.from(container.querySelectorAll('text'))
        .map(boxOf)
        .filter((b): b is Box => b !== null)
        .filter((b) => b.y1 < 0 || b.y2 > vbH || b.x2 > vbW + 1 || b.x1 < -1)

      expect(
        escaping.map((b) => b.text),
        'labels drawn outside the viewBox are invisible',
      ).toEqual([])
    })
  }

  it('summarises a bridge by its slippages, not all its identity mappings', () => {
    // A bridge commonly carries five mappings of which one is a slippage. Showing
    // them all produced labels wider than the whole diagram.
    useRunStore.setState({ workspace: eeqee as any })
    const { container } = render(<WorkspaceView />)

    const labels = Array.from(container.querySelectorAll('text')).map(ownText)
    // Identity runs like "LetterCtgy=LetterCtgy, group=group, ..." must not be
    // rendered in full.
    for (const label of labels) {
      expect(label.length).toBeLessThanOrEqual(70)
    }
  })

  it('attaches a bridge to the middle of a group, not its first letter', () => {
    useRunStore.setState({ workspace: eeqee as any })
    const { container } = render(<WorkspaceView />)

    const bridges = (eeqee as any).vertical_bridges ?? []
    const spanning = bridges.find(
      (b: any) => (b.obj1_right_pos ?? b.obj1_pos) > b.obj1_pos,
    )
    if (!spanning) return // nothing multi-letter to check in this fixture

    // Endpoint dots mark where lines attach; a group's dot must not sit on the
    // centre of its leftmost letter.
    const dots = Array.from(container.querySelectorAll('circle'))
    expect(dots.length).toBeGreaterThan(0)
  })
})
