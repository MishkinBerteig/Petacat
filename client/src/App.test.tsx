// ---------------------------------------------------------------------------
// App's routing of the configuration deep link (SMKFIX)
// ---------------------------------------------------------------------------
//
// `#/config?configuration=<id>` must reach the configuration editors (AdminLayout), not the Admin
// (Metacat Mode) page, and the Configurations view must not be labelled as Metacat Mode's.
// Every heavy panel is replaced; App, the menu and AdminLayout are real.
// ---------------------------------------------------------------------------
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

const stub = vi.hoisted(() => (name: string) => () => document.createElement('i') && null)
vi.mock('@/hooks/useWebSocket', () => ({ useWebSocket: () => {} }))
vi.mock('@/components/AdminPanel', () => ({ AdminPanel: () => <div data-testid="admin-panel" /> }))
vi.mock('@/components/ProblemInputPanel', () => ({ ProblemInputPanel: stub('input') }))
vi.mock('@/components/RunControlsPanel', () => ({ RunControlsPanel: stub('controls') }))
vi.mock('@/components/WorkspaceView', () => ({ WorkspaceView: stub('workspace') }))
vi.mock('@/components/SlipnetView', () => ({ SlipnetView: stub('slipnet') }))
vi.mock('@/components/CoderackView', () => ({ CoderackView: stub('coderack') }))
vi.mock('@/components/EegView', () => ({ EegView: stub('eeg') }))
vi.mock('@/components/ThemespaceView', () => ({ ThemespaceView: stub('themespace') }))
vi.mock('@/components/TraceView', () => ({ TraceView: stub('trace') }))
vi.mock('@/components/MemoryView', () => ({ MemoryView: stub('memory') }))
vi.mock('@/components/TemperatureGauge', () => ({ TemperatureGauge: stub('temp') }))
vi.mock('@/components/CommentaryPanel', () => ({ CommentaryPanel: stub('commentary') }))
vi.mock('@/components/VerbosePanel', () => ({ VerbosePanel: stub('verbose') }))
vi.mock('@/components/RunHistory', () => ({ RunHistory: stub('history') }))
vi.mock('@/components/review/ReviewPanel', () => ({ ReviewPanel: stub('review') }))
vi.mock('@/components/session/SessionPanel', () => ({ SessionPanel: stub('session') }))
vi.mock('@/components/SubstrateBadge', () => ({ SubstrateBadge: () => null }))
vi.mock('@/components/WindowsMenu', () => ({ WindowsMenu: stub('windows') }))
vi.mock('@/components/SearchPalette', () => ({ SearchPalette: () => null }))
vi.mock('@/components/HelpPopover', () => ({ HelpPopover: () => null }))
vi.mock('@/components/LastErrorBanner', () => ({ LastErrorBanner: () => null }))

import App from './App'

function reply(body: unknown) {
  const text = JSON.stringify(body)
  return { ok: true, status: 200, statusText: '', text: async () => text, json: async () => JSON.parse(text) } as unknown as Response
}

const SESSION_CONFIG = {
  id: 5, name: 'Alpha', note: '', kind: 'session', mode: 'Training Mode',
  mode_label: 'Training Mode: Alpha', session_id: 7, session_name: 'Alpha', session_state: 'stopped',
  revision: 4, config_hash: 'a', frozen: false, created_from_configuration_id: null,
  equals_standard: false, differs_from_standard_rows: 1, last_change: null, source: 'stored',
}

function serve() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = String(url).replace('/api', '')
    if (path === '/configurations/5') return reply(SESSION_CONFIG)
    if (/^\/configurations\/\d+\/status/.test(path)) return reply({ differs_rows: 0, equals_standard: true })
    if (/^\/configurations\/\d+\/rows/.test(path)) return reply({ key_columns: ['name'], rows: [] })
    return reply([])
  }))
}

afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

describe('App routing of the configuration deep link', () => {
  it('opens the configuration editors, on that configuration, when the page loads on the link', async () => {
    serve()
    window.location.hash = '#/config?configuration=5'
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain("Training Mode Session 'Alpha'"))
    expect(screen.queryByTestId('admin-panel')).toBeNull()
  })

  it('opens it when the link is followed while another view is shown', async () => {
    serve()
    window.location.hash = '#/'
    render(<App />)
    expect(screen.queryByTestId('configuration-chip')).toBeNull()
    await act(async () => {
      window.location.hash = '#/config?configuration=5'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(screen.getByTestId('configuration-chip').textContent).toContain("Training Mode Session 'Alpha'"))
    expect(screen.queryByTestId('admin-panel')).toBeNull()
    expect(window.location.hash).toBe('#/config?configuration=5')
  })

  it('still routes #/config/slipnet/<node> to the editors and #/admin to the Admin page', async () => {
    serve()
    window.location.hash = '#/config/slipnet/plato-a'
    const { unmount } = render(<App />)
    await screen.findByText('Slipnet Nodes')
    expect(screen.queryByTestId('admin-panel')).toBeNull()
    unmount()
    window.location.hash = '#/admin'
    render(<App />)
    expect(await screen.findByTestId('admin-panel')).toBeTruthy()
  })

  it('labels the Configurations view for both modes, and the Admin view as before', async () => {
    serve()
    window.location.hash = '#/config'
    render(<App />)
    const header = "Configurations — Metacat Mode's global configuration and each Training Mode Session's own. The chip below names the one open."
    expect(document.querySelector('.app-header')?.textContent).toContain(header)
    expect(document.querySelector('.app-header')?.getAttribute('data-mode')).toBe('configurations')
    fireEvent.click(screen.getByRole('button', { name: 'Navigation menu' }))
    expect(screen.getByRole('button', { name: /Configurations \(Metacat Mode and Training Mode\)/ })).toBeTruthy()
  })
})
