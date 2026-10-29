// ---------------------------------------------------------------------------
// Petacat -- clicking a Trace event, an answer or a snag redisplays the moment
// ---------------------------------------------------------------------------
//
// Metacat's `display` methods (`trace.ss:405-1250`, `memory.ss:268-395`) redraw the
// Workspace for the moment under a header ("Event N:  Built successor-group"), highlight
// the moment's structures, show its concept pattern in the Slipnet, blank the Coderack
// (or show a clamp's codelet pattern) and show the moment's temperature. The windows
// read what is on show from the moment store; the Trace and Memory panels put it there.
// The labels of the Trace window are the events' print names (`trace.ss`).
// ---------------------------------------------------------------------------

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

import { WorkspaceDiagram } from './WorkspaceView'
import { WorkspaceView } from './WorkspaceView'
import { TraceList, TraceView } from './TraceView'
import { MemoryView } from './MemoryView'
import { CoderackView } from './CoderackView'
import { TemperatureGauge } from './TemperatureGauge'
import { momentSlipnet } from './SlipnetView'
import { useMomentStore } from '@/store/momentStore'
import { useRunStore } from '@/store/runStore'
import type { DisplayPicture, TraceEvent, WorkspaceState } from '@/types'

const group = (left: number, right: number) => ({
  left_pos: left,
  right_pos: right,
  category: 'succgrp',
  direction: 'right',
  strength: 80,
  built: true,
  depth: 0,
  length: right - left + 1,
})

const bridge = (o1: number, o2: number, slip = false) => ({
  obj1_string: 'abc',
  obj1_pos: o1,
  obj1_right_pos: o1,
  obj2_string: 'ijk',
  obj2_pos: o2,
  obj2_right_pos: o2,
  strength: 90,
  built: true,
  concept_mappings: [
    { from: 'rmost', to: 'rmost', label: 'Identity', is_slippage: false },
    ...(slip ? [{ from: 'first', to: 'last', label: 'opposite', is_slippage: true }] : []),
  ],
})

const workspace: WorkspaceState = {
  initial: 'abc',
  modified: 'abd',
  target: 'ijk',
  answer: null,
  num_top_bridges: 0,
  num_bottom_bridges: 0,
  num_vertical_bridges: 2,
  num_top_rules: 0,
  num_bottom_rules: 0,
  bonds_per_string: {},
  groups_per_string: { abc: 1, ijk: 1 },
  bonds: {},
  groups: { abc: [group(0, 2)], abd: [], ijk: [group(0, 2)] },
  top_bridges: [],
  vertical_bridges: [bridge(0, 0, true), bridge(2, 2)],
  bottom_bridges: [],
  top_rules: [],
  bottom_rules: [
    {
      type: 'bottom',
      quality: 50,
      uniformity: 100,
      abstractness: 50,
      succinctness: 50,
      clause_count: 1,
      verbatim: false,
      english: 'Change letter-category of rightmost letter to successor',
      built: false,
      theme_pattern: [],
      role: 'snag',
    },
  ],
}

function picture(overrides: Partial<DisplayPicture> = {}): DisplayPicture {
  return {
    version: 1,
    kind: 'event',
    header: 'Built successor-group',
    codelet_count: 113,
    temperature: 84,
    faded: true,
    workspace,
    highlights: {
      groups: [{ string: 'initial', left: 0, right: 2, role: 'event' }],
      objects: [{ string: 'initial', left: 0, right: 2, role: 'event' }],
      bridges: [{ key: 'vertical:0-0:0-0', role: 'vertical' }],
      concept_mappings: [
        { bridge: 'vertical:0-0:0-0', from: 'first', to: 'last', role: 'theme_cm' },
      ],
    },
    slipnet: {
      title: 'Group Descriptors',
      entries: [
        { node: 'plato-succgrp', activation: 100 },
        { node: 'plato-letter-category', activation: 0 },
      ],
    },
    coderack: { title: 'Coderack', entries: [], blank: true },
    themes: [],
    question_mark: false,
    ...overrides,
  }
}

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  useRunStore.setState({ ...ORIGINAL }, true)
  useMomentStore.setState({ displayed: null, onShow: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('WorkspaceDiagram — a redisplayed moment', () => {
  it('heads the picture with "Event N:" and the event header', () => {
    render(<WorkspaceDiagram workspace={workspace} picture={picture()} eventNumber={2} />)
    expect(screen.getByTestId('moment-header').textContent).toBe(
      'Event 2:  Built successor-group',
    )
  })

  it('heads an answer or snag description with its own title and no event number', () => {
    render(
      <WorkspaceDiagram
        workspace={workspace}
        picture={picture({ kind: 'description', header: 'Answer Description', faded: false })}
      />,
    )
    expect(screen.getByTestId('moment-header').textContent).toBe('Answer Description')
  })

  it('draws the live Workspace with no header', () => {
    render(<WorkspaceDiagram workspace={workspace} />)
    expect(screen.queryByTestId('moment-header')).toBeNull()
    expect(document.querySelector('[data-highlight]')).toBeNull()
  })

  it('highlights the named object and fades the other groups', () => {
    const { container } = render(
      <WorkspaceDiagram workspace={workspace} picture={picture()} eventNumber={2} />,
    )
    const marks = container.querySelectorAll('rect[data-highlight="event"]')
    expect(marks.length).toBe(1)
    // The two group boxes: the highlighted one in the event colour, the other faded.
    const strokes = Array.from(container.querySelectorAll('rect[rx="5"]')).map((r) =>
      r.getAttribute('stroke'),
    )
    expect(strokes).toContain('#ffd700')
    expect(strokes).toContain('var(--text-secondary)')
  })

  it('colours the named bridge and leaves the others faded', () => {
    const { container } = render(
      <WorkspaceDiagram workspace={workspace} picture={picture()} eventNumber={2} />,
    )
    const paths = Array.from(container.querySelectorAll('path')).filter((p) =>
      (p.getAttribute('d') ?? '').includes('Q'),
    )
    const colours = paths.map((p) => p.getAttribute('stroke'))
    expect(colours).toContain('#ab47bc')
    expect(colours).toContain('var(--text-secondary)')
  })

  it('marks the concept-mapping a moment names in the bridge key', () => {
    const { container } = render(
      <WorkspaceDiagram workspace={workspace} picture={picture()} eventNumber={2} />,
    )
    const marked = container.querySelector('tspan[data-highlight="theme_cm"]')
    expect(marked?.textContent).toContain('first⇒last')
  })

  it('draws "???" for a snag and colours the translated rule that failed', () => {
    const { container } = render(
      <WorkspaceDiagram
        workspace={workspace}
        picture={picture({ header: 'Snag', question_mark: true })}
        eventNumber={9}
      />,
    )
    expect(screen.getByTestId('snag-question-marks').textContent).toBe('???')
    const rule = container.querySelector('[data-testid="rule-box"]') as HTMLElement
    expect(rule.style.border).toContain('2px solid')
  })
})

describe('WorkspaceView — reads what is on show', () => {
  it('redraws the Workspace from the displayed moment', () => {
    useMomentStore.setState({
      displayed: { kind: 'event', id: 2, eventNumber: 2, picture: picture() },
      onShow: { kind: 'event', id: 2 },
    })
    render(<WorkspaceView />)
    expect(screen.getByTestId('moment-header').textContent).toContain('Event 2')
  })
})

describe('the other windows follow the moment', () => {
  it('shows the moment’s temperature in the gauge', () => {
    useRunStore.setState({ runId: 7, temperature: 42 })
    useMomentStore.setState({
      displayed: { kind: 'event', id: 2, eventNumber: 2, picture: picture({ temperature: 84 }) },
      onShow: { kind: 'event', id: 2 },
    })
    render(<TemperatureGauge />)
    expect(screen.getByText('84')).toBeTruthy()
    expect(screen.queryByText('42')).toBeNull()
  })

  it('blanks the Coderack under its title', () => {
    useMomentStore.setState({
      displayed: { kind: 'event', id: 2, eventNumber: 2, picture: picture() },
      onShow: { kind: 'event', id: 2 },
    })
    render(<CoderackView />)
    expect(screen.getByTestId('coderack-moment').textContent).toContain('Coderack')
  })

  it('shows a clamp’s codelet pattern in the Coderack', () => {
    useMomentStore.setState({
      displayed: {
        kind: 'event',
        id: 5,
        eventNumber: 5,
        picture: picture({
          coderack: {
            title: 'Codelet Pattern',
            entries: [{ type: 'rule-scout', urgency: 91 }],
          },
        }),
      },
      onShow: { kind: 'event', id: 5 },
    })
    render(<CoderackView />)
    const box = screen.getByTestId('coderack-moment')
    expect(box.textContent).toContain('Codelet Pattern')
    expect(box.textContent).toContain('rule-scout')
  })

  it('lights only the pattern’s nodes in the Slipnet, at the pattern’s activation', () => {
    const live = {
      'plato-succgrp': { activation: 12, conceptual_depth: 60, frozen: false },
      'plato-letter-category': { activation: 70, conceptual_depth: 30, frozen: true },
      'plato-a': { activation: 40, conceptual_depth: 10, frozen: false },
    }
    const shown = momentSlipnet(live, picture())
    expect(shown['plato-succgrp'].activation).toBe(100)
    expect(shown['plato-letter-category'].activation).toBe(0)
    expect(shown['plato-a'].activation).toBe(0)
    expect(shown['plato-letter-category'].frozen).toBe(false)
  })

  it('blanks the Slipnet for a moment with no pattern', () => {
    const live = { 'plato-a': { activation: 40, conceptual_depth: 10, frozen: false } }
    const shown = momentSlipnet(
      live,
      picture({ slipnet: { title: 'Slipnet Activation', entries: [], blank: true } }),
    )
    expect(shown['plato-a'].activation).toBe(0)
  })
})

describe('the moment store', () => {
  it('puts a picture on show and clears it when the live state is restored', () => {
    const { show } = useMomentStore.getState()
    show('event', 3, { displaying: 3, picture: picture() }, 3)
    expect(useMomentStore.getState().displayed?.picture.header).toBe('Built successor-group')
    expect(useMomentStore.getState().onShow).toEqual({ kind: 'event', id: 3 })
    show('event', 3, { displaying: null, picture: null }, 3)
    expect(useMomentStore.getState().displayed).toBeNull()
    expect(useMomentStore.getState().onShow).toBeNull()
  })

  it('marks a moment as selected even when no picture was kept for it', () => {
    // An event stored before pictures were: only the Themespace moves.
    useMomentStore.getState().show('answer', 4, { displaying: 4, picture: null })
    expect(useMomentStore.getState().displayed).toBeNull()
    expect(useMomentStore.getState().onShow).toEqual({ kind: 'answer', id: 4 })
  })

  it('forgets what was on show when another run is loaded', () => {
    useRunStore.setState({ runId: 1 })
    useMomentStore.getState().show('event', 3, { displaying: 3, picture: picture() }, 3)
    act(() => useRunStore.setState({ runId: 2 }))
    expect(useMomentStore.getState().displayed).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// The Trace window
// ---------------------------------------------------------------------------

const events: TraceEvent[] = [
  {
    event_number: 1,
    event_type: 'concept_activation',
    codelet_count: 52,
    temperature: 96,
    description: 'the concept of Identity became active',
    print_name: '(Identity)',
  },
  {
    event_number: 2,
    event_type: 'group_built',
    codelet_count: 113,
    temperature: 84,
    description: 'perceived ijk group',
    print_name: '>i-j-k>',
  },
  {
    event_number: 3,
    event_type: 'rule_built',
    codelet_count: 635,
    temperature: 49,
    description: 'Change letter-category of rightmost letter to successor',
    print_name: '[Top Rule]',
  },
  {
    // Stored before print names were kept.
    event_number: 4,
    event_type: 'answer_found',
    codelet_count: 711,
    temperature: 18,
    description: "Answer 'ijl' found with quality 88",
  },
]

describe('the Trace window labels', () => {
  it('draws each event by its Metacat print name', () => {
    render(<TraceList trace={events} />)
    const labels = screen.getAllByTestId('event-print-name').map((e) => e.textContent)
    expect(labels).toEqual([
      '(Identity)',
      '>i-j-k>',
      '[Top Rule]',
      "Answer 'ijl' found with quality 88",
    ])
  })

  it('keeps the longer prose as the tooltip, not the label', () => {
    render(<TraceList trace={events} />)
    expect(screen.getByText('>i-j-k>').getAttribute('title')).toBe('perceived ijk group')
  })

  it('finds an event by its print name', () => {
    render(<TraceList trace={events} />)
    fireEvent.change(screen.getByPlaceholderText('Search...'), { target: { value: '[top' } })
    expect(screen.getAllByTestId('event-print-name').map((e) => e.textContent)).toEqual([
      '[Top Rule]',
    ])
  })
})

function reply(body: unknown) {
  return { ok: true, status: 200, statusText: 'OK', json: async () => body, text: async () => '' }
}

describe('clicking a Trace event', () => {
  it('puts the event’s picture on show, and clicking it again restores the live windows', async () => {
    const shown = { displaying: 2, picture: picture(), print_name: '>i-j-k>' }
    const restored = { displaying: null, picture: null }
    const calls: string[] = []
    let next: unknown = shown
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        calls.push(url)
        return reply(url.includes('/display') ? next : {})
      }),
    )
    useRunStore.setState({ runId: 7, trace: events })

    render(<TraceView />)
    fireEvent.click(screen.getByText('>i-j-k>'))
    await waitFor(() => expect(useMomentStore.getState().displayed).not.toBeNull())
    expect(useMomentStore.getState().displayed?.eventNumber).toBe(2)
    expect(calls.some((c) => c.endsWith('/runs/7/trace/2/display'))).toBe(true)

    next = restored
    fireEvent.click(screen.getByText('>i-j-k>'))
    await waitFor(() => expect(useMomentStore.getState().displayed).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// The Memory window
// ---------------------------------------------------------------------------

describe('clicking a snag in the Memory window', () => {
  it('displays the snag’s picture and restores it on a second click', async () => {
    const snagPicture = picture({
      kind: 'description',
      header: 'Snag Description',
      faded: false,
      question_mark: true,
      temperature: 100,
    })
    let next: unknown = { displaying: 3, picture: snagPicture, temperature: 100 }
    const calls: string[] = []
    const memory = {
      answers: [],
      snags: [
        {
          snag_id: 3,
          problem: ['abc', 'abd', 'xyz'],
          codelet_count: 421,
          temperature: 100,
          description: 'replace rightmost letter by successor',
          has_picture: true,
        },
      ],
    }
    useRunStore.setState({ runId: 7, memory })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        calls.push(url)
        if (url.includes('/snags/3/display')) return reply(next)
        if (url.endsWith('/memory')) return reply(memory)
        return reply({})
      }),
    )

    render(<MemoryView />)
    const button = await screen.findByTestId('snag-display')
    fireEvent.click(button)
    await waitFor(() => expect(useMomentStore.getState().displayed?.kind).toBe('snag'))
    expect(calls.some((c) => c.includes('/api/memory/snags/3/display?run_id=7'))).toBe(true)
    expect(useMomentStore.getState().displayed?.picture.header).toBe('Snag Description')
    await waitFor(() => expect(screen.getByTestId('snag-display').textContent).toBe('restore'))

    next = { displaying: null, picture: null }
    fireEvent.click(screen.getByTestId('snag-display'))
    await waitFor(() => expect(useMomentStore.getState().displayed).toBeNull())
  })
})
