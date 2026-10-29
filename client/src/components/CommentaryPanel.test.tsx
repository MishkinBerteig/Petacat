// ---------------------------------------------------------------------------
// Petacat -- an empty commentary panel has two different causes
// ---------------------------------------------------------------------------
//
// Phase 0's WP3.10 made commentary a sink concern: the engine calls `emit_*`
// unconditionally, and in a Fast Run those calls land on a discarding writer. A
// Fast Run that has answered therefore returns zero paragraphs, and the panel's
// ordinary empty message -- "start a run to see commentary" -- is then advice to do
// the thing that has already been done.
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { CommentaryPanel, commentaryFilename } from './CommentaryPanel'
import { useRunStore } from '@/store/runStore'

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
})

describe('CommentaryPanel', () => {
  it('shows the commentary when there is any', () => {
    useRunStore.setState({ commentary: 'I noticed a successor group.', runMode: 'normal' })
    render(<CommentaryPanel />)
    expect(screen.getByText(/I noticed a successor group/)).toBeTruthy()
  })

  it('shows a Fast run its commentary, which it narrates like any other run', () => {
    useRunStore.setState({
      commentary: 'I noticed a successor group.',
      runMode: 'fast',
      runId: -1,
      codeletCount: 2229,
    })
    render(<CommentaryPanel />)
    expect(screen.getByText(/I noticed a successor group/)).toBeTruthy()
  })

  it('keeps the ordinary invitation when no run has been started', () => {
    useRunStore.setState({ commentary: '', runMode: null, runId: null })
    render(<CommentaryPanel />)
    expect(screen.getByText(/Start a run to see commentary/)).toBeTruthy()
  })
})

describe('CommentaryPanel — Save commentary to file', () => {
  it('saves the commentary on screen as a text file named for the run and voice', async () => {
    const urls: Blob[] = []
    ;(URL as any).createObjectURL = (b: Blob) => { urls.push(b); return 'blob:x' }
    ;(URL as any).revokeObjectURL = () => {}
    let downloaded = ''
    const click = HTMLAnchorElement.prototype.click
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) { downloaded = this.download }
    try {
      useRunStore.setState({
        commentary: 'First paragraph.\n\nSecond paragraph.',
        runId: 7,
        elizaMode: false,
      })
      render(<CommentaryPanel />)
      fireEvent.click(screen.getByRole('button', { name: 'Save commentary to file' }))
      expect(downloaded).toBe('petacat-commentary-run-7-technical.txt')
      const read = (b: Blob) => new Promise<string>((resolve) => {
        const r = new FileReader()
        r.onload = () => resolve(String(r.result))
        r.readAsText(b)
      })
      expect(await read(urls[0])).toBe('First paragraph.\n\nSecond paragraph.\n')
    } finally {
      HTMLAnchorElement.prototype.click = click
    }
  })

  it('has nothing to save before there is commentary', () => {
    useRunStore.setState({ commentary: '', runId: null })
    render(<CommentaryPanel />)
    expect((screen.getByRole('button', { name: 'Save commentary to file' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('names the voice in the file', () => {
    expect(commentaryFilename(3, true)).toBe('petacat-commentary-run-3-eliza.txt')
    expect(commentaryFilename(null, false)).toBe('petacat-commentary-technical.txt')
  })
})

describe('CommentaryPanel — font menus', () => {
  it('offers face and size as Metacat\'s Options menu does', () => {
    useRunStore.setState({ commentary: 'Hello.' })
    render(<CommentaryPanel />)
    const size = screen.getByLabelText('Commentary font size') as HTMLSelectElement
    expect([...size.options].map((o) => o.value)).toEqual(['tiny', 'small', 'medium', 'large', 'larger', 'huge'])
    fireEvent.change(size, { target: { value: 'huge' } })
    expect((screen.getByText('Hello.') as HTMLElement).style.fontSize).toBe('34px')
    const face = screen.getByLabelText('Commentary font face') as HTMLSelectElement
    expect([...face.options].map((o) => o.value)).toEqual(['serif', 'sans-serif', 'fancy'])
  })
})
