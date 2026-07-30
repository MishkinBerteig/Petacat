// ---------------------------------------------------------------------------
// Petacat -- the twenty-five fixed run parameters, settable before a run
// ---------------------------------------------------------------------------
//
// The claims worth holding onto here are the ones with a plausible wrong version:
//
//   1. The form is built from the server's catalogue, not from a list in the
//      client. The wrong version hardcodes twenty-five controls and drifts from
//      the bounds the API validates against, so the form offers values the server
//      refuses.
//   2. A value out of range is refused *before* the request. The wrong version
//      sends it and surfaces a 400 with nothing on screen to attach it to.
//   3. Resetting removes the override rather than pinning the parameter to today's
//      default. The two are indistinguishable until somebody edits the default in
//      the Admin panel, at which point a pinned value is an override nobody chose.
//   4. `node_list` and `node_map` are shown, in full, and are not editable. The
//      wrong versions are a broken text editor, or omitting them and quietly
//      showing twenty-two of twenty-five.
// ---------------------------------------------------------------------------

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { RunParametersPanel } from './RunParametersPanel'
import { useRunStore } from '@/store/runStore'
import { useParameterCatalogueStore } from '@/hooks/useParameterCatalogue'
import { getParameterCatalogue } from '@/api/client'
import type { RunParameterSpec } from '@/types'

vi.mock('@/api/client', () => ({
  getParameterCatalogue: vi.fn(),
}))

const mockedCatalogue = vi.mocked(getParameterCatalogue)

function spec(overrides: Partial<RunParameterSpec> = {}): RunParameterSpec {
  return {
    name: 'update_cycle_length',
    kind: 'int',
    group: 'Temperature and pacing',
    label: 'Update cycle length',
    description:
      'How many codelets run between full recomputations of strengths, saliences, '
      + 'activations and temperature.',
    minimum: 1,
    maximum: 1000,
    departs_from_original: true,
    default: 15,
    ...overrides,
  }
}

const CATALOGUE: RunParameterSpec[] = [
  spec(),
  spec({
    name: 'verbatim_rule_probability',
    kind: 'float',
    group: 'Coderack',
    label: 'Verbatim rule probability',
    description: 'The chance a rule scout ignores the bridges.',
    minimum: 0,
    maximum: 1,
    default: 0.05,
  }),
  spec({
    name: 'self_watching_enabled_default',
    kind: 'bool',
    group: 'Self-watching',
    label: 'Self-watching enabled',
    description: 'Whether the Themespace, progress-watchers and jootsers run at all.',
    minimum: null,
    maximum: null,
    default: true,
  }),
  spec({
    name: 'initially_clamped_slipnodes',
    kind: 'node_list',
    group: 'Slipnet',
    label: 'Initially clamped nodes',
    description: 'Which concepts are held active during the warm-up.',
    minimum: null,
    maximum: null,
    default: ['plato-letter-category', 'plato-string-position-category'],
  }),
  spec({
    name: 'intrinsic_link_lengths',
    kind: 'node_map',
    group: 'Slipnet',
    label: 'Intrinsic link lengths',
    description: 'The conceptual distance of each labelled link.',
    minimum: null,
    maximum: null,
    default: { 'plato-identity': 0, 'plato-opposite': 90 },
  }),
]

const ORIGINAL = useRunStore.getState()

beforeEach(() => {
  mockedCatalogue.mockReset()
  mockedCatalogue.mockResolvedValue(CATALOGUE)
  useRunStore.setState({ ...ORIGINAL, parameterOverrides: {} }, true)
  // The catalogue store is shared and fetches once, so it has to be emptied between
  // tests or the second test sees the first one's answer and never calls the mock.
  useParameterCatalogueStore.setState({ specs: [], isLoading: false, error: null })
})

/**
 * The number field for a parameter.
 *
 * By role rather than by label text: every parameter also has a "?" button and a
 * reset button whose accessible names contain the same label, so `getByLabelText`
 * matches three elements.
 */
function spinbutton(name: RegExp): HTMLInputElement {
  return screen.getByRole('spinbutton', { name }) as HTMLInputElement
}

/** Open the section and the group holding `label`. */
async function open(groupLabel: string) {
  fireEvent.click(screen.getByRole('button', { name: /engine parameters/i }))
  await waitFor(() => expect(mockedCatalogue).toHaveBeenCalled())
  const group = await screen.findByRole('button', { name: new RegExp(groupLabel, 'i') })
  if (group.getAttribute('aria-expanded') === 'false') fireEvent.click(group)
}

describe('RunParametersPanel — driven by the server catalogue', () => {
  it('renders a control per parameter, grouped as the catalogue groups them', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    expect(spinbutton(/Update cycle length/)).toBeTruthy()
    // Every group the catalogue names has a header, whether or not it is expanded.
    for (const group of ['Temperature and pacing', 'Coderack', 'Self-watching', 'Slipnet']) {
      expect(screen.getByRole('button', { name: new RegExp(group, 'i') })).toBeTruthy()
    }
  })

  it('enforces the server\'s own bounds on the control', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    const input = spinbutton(/Update cycle length/)
    expect(input.min).toBe('1')
    expect(input.max).toBe('1000')
  })

  it('shows each parameter\'s default, and an empty field means it', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    const input = spinbutton(/Update cycle length/)
    expect(input.value).toBe('')
    expect(input.placeholder).toBe('15')
    // The default is also written out beside the name, so it is legible without
    // having to notice that the placeholder is one.
    expect(
      screen.getByText((_, el) => el?.textContent === 'update_cycle_length · default 15 · 1–1000'),
    ).toBeTruthy()
  })

  it('records a changed value as an override and says how many are changed', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    fireEvent.change(spinbutton(/Update cycle length/), {
      target: { value: '40' },
    })

    expect(useRunStore.getState().parameterOverrides).toEqual({ update_cycle_length: 40 })
    expect(screen.getByText(/1 changed/)).toBeTruthy()
  })

  it('says on the control which parameters are out of the range the server accepts', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    fireEvent.change(spinbutton(/Update cycle length/), {
      target: { value: '5000' },
    })

    expect(screen.getByText(/must be at most 1000/)).toBeTruthy()
  })

  it('drops the override when the default is typed back in, rather than pinning it', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    const input = spinbutton(/Update cycle length/)
    fireEvent.change(input, { target: { value: '40' } })
    fireEvent.change(input, { target: { value: '15' } })

    expect(useRunStore.getState().parameterOverrides).toEqual({})
  })

  it('resets one parameter', async () => {
    render(<RunParametersPanel />)
    await open('Temperature and pacing')

    fireEvent.change(spinbutton(/Update cycle length/), {
      target: { value: '40' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: /Reset Update cycle length to its default/i }),
    )

    expect(useRunStore.getState().parameterOverrides).toEqual({})
  })

  it('resets all of them at once', async () => {
    useRunStore.setState({
      parameterOverrides: { update_cycle_length: 40, verbatim_rule_probability: 0.5 },
    })
    render(<RunParametersPanel />)
    fireEvent.click(screen.getByRole('button', { name: /engine parameters/i }))
    await waitFor(() => expect(mockedCatalogue).toHaveBeenCalled())

    fireEvent.click(await screen.findByRole('button', { name: /Reset all 2 to defaults/i }))
    expect(useRunStore.getState().parameterOverrides).toEqual({})
  })

  it('offers a checkbox for a boolean rather than a number field', async () => {
    render(<RunParametersPanel />)
    await open('Self-watching')

    const box = screen.getByRole('checkbox', { name: /Self-watching enabled/ }) as HTMLInputElement
    expect(box.type).toBe('checkbox')
    expect(box.checked).toBe(true)

    fireEvent.click(box)
    expect(useRunStore.getState().parameterOverrides).toEqual({
      self_watching_enabled_default: false,
    })
  })
})

describe('RunParametersPanel — twenty-five controls without swamping the panel', () => {
  it('is collapsed until asked for, and the common path is untouched', () => {
    render(<RunParametersPanel />)

    expect(screen.queryByRole('spinbutton', { name: /Update cycle length/ })).toBeNull()
    expect(screen.getByText(/Every parameter at its default/)).toBeTruthy()
  })

  it('carries the count of changed parameters while closed', async () => {
    useRunStore.setState({ parameterOverrides: { update_cycle_length: 40 } })
    render(<RunParametersPanel />)
    // The catalogue is needed to know which values differ from their defaults.
    useParameterCatalogueStore.setState({ specs: CATALOGUE })

    await waitFor(() => expect(screen.getByText(/1 changed/)).toBeTruthy())
    expect(screen.queryByRole('spinbutton', { name: /Update cycle length/ })).toBeNull()
  })

  it('opens a group by itself when it holds a changed value', async () => {
    useRunStore.setState({ parameterOverrides: { verbatim_rule_probability: 0.5 } })
    render(<RunParametersPanel />)
    fireEvent.click(screen.getByRole('button', { name: /engine parameters/i }))

    // Not clicked open: the Coderack group expands because something in it changed,
    // which is what stops "2 changed" being a count with nothing behind it.
    await waitFor(() =>
      expect(spinbutton(/Verbatim rule probability/)).toBeTruthy(),
    )
    expect(screen.queryByRole('spinbutton', { name: /Update cycle length/ })).toBeNull()
  })
})

describe('RunParametersPanel — the two kinds with no honest control', () => {
  it('shows a node list in full and says it is read-only here', async () => {
    render(<RunParametersPanel />)
    await open('Slipnet')

    expect(screen.getByText('plato-letter-category')).toBeTruthy()
    expect(screen.getByText('plato-string-position-category')).toBeTruthy()
    expect(screen.getAllByText(/read-only/i).length).toBeGreaterThan(0)
    expect(
      screen.getAllByText(/Configuration → Engine Params/).length,
    ).toBeGreaterThan(0)
  })

  it('shows a node map with its values, and offers no field for it', async () => {
    render(<RunParametersPanel />)
    await open('Slipnet')

    expect(screen.getByText('plato-opposite:90')).toBeTruthy()
    expect(screen.queryByRole('spinbutton', { name: /Intrinsic link lengths/ })).toBeNull()
  })
})
