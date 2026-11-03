import { useCallback, useEffect, useMemo, useState } from 'react'
import { describeApiError, listConfigurations, patchConfiguration } from '@/api/client'
import type { ConfigurationSummary } from '@/types/configuration'
import { ConfigurationCompare } from './ConfigurationCompare'
import { BADGE_COLORS, badgeMode, badgeText, METACAT_MODE, TRAINING_MODE } from './configurationLabels'

type SortKey = 'name' | 'mode' | 'revision' | 'differs' | 'changed'
type ModeFilter = 'all' | typeof METACAT_MODE | typeof TRAINING_MODE

const SORTS: Record<SortKey, (c: ConfigurationSummary) => string | number> = {
  name: c => c.name.toLowerCase(),
  mode: c => badgeText(c).toLowerCase(),
  revision: c => c.revision,
  differs: c => c.differs_from_standard_rows,
  changed: c => c.last_change?.recorded_at ?? '',
}

/** The new session form is the Training Mode view's; the hash carries the base to it. */
export function newSessionHash(c: ConfigurationSummary): string {
  const base = c.kind === 'global' || c.session_id == null ? 'global' : `session:${c.session_id}`
  const name = c.kind === 'session' ? `&name=${encodeURIComponent(c.session_name ?? c.name)}` : ''
  return `/training-mode/new?base=${base}${name}`
}

const lastChange = (c: ConfigurationSummary) => {
  const l = c.last_change
  if (!l) return 'none'
  const at = l.recorded_at ? new Date(l.recorded_at).toLocaleString() : 'unknown time'
  return `${at} (${l.source}, ${l.actor}, ${l.channel})`
}

/**
 * The configuration manager: one row per configuration, with its mode badge, revision, frozen
 * flag, how far it differs from the Metacat Standard Configuration and its last change. A row
 * opens in the editors, goes to History, starts a new Training Mode Session from it, or is
 * frozen. Compare is below the list.
 */
export function ConfigurationsTab({
  openId,
  onOpen,
  onHistory,
  onChanged,
  refreshKey,
}: {
  openId: number
  onOpen: (id: number) => void
  onHistory: (id: number) => void
  onChanged?: () => void
  refreshKey?: unknown
}) {
  const [items, setItems] = useState<ConfigurationSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<ModeFilter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [descending, setDescending] = useState(false)
  const [compareFrom, setCompareFrom] = useState<number | null>(null)
  const [version, setVersion] = useState(0)

  const load = useCallback(() => {
    listConfigurations()
      .then(list => { setItems(list); setError(null) })
      .catch(err => setError(describeApiError(err, 'load the configurations')))
  }, [])

  useEffect(() => { load() }, [load, refreshKey, version])

  const shown = useMemo(() => {
    const list = (items ?? []).filter(c => filter === 'all' || badgeMode(c) === filter)
    const key = SORTS[sortKey]
    list.sort((x, y) => {
      const a = key(x), b = key(y)
      return (a < b ? -1 : a > b ? 1 : 0) * (descending ? -1 : 1)
    })
    return list
  }, [items, filter, sortKey, descending])

  const sortBy = (k: SortKey) => {
    if (k === sortKey) setDescending(d => !d)
    else { setSortKey(k); setDescending(false) }
  }

  const toggleFrozen = async (c: ConfigurationSummary) => {
    try {
      await patchConfiguration(c.id, { frozen: !c.frozen })
      setVersion(v => v + 1)
      onChanged?.()
    } catch (err) {
      setError(describeApiError(err, c.frozen ? 'unfreeze the configuration' : 'freeze the configuration'))
    }
  }

  const newSession = (c: ConfigurationSummary) => { window.location.hash = newSessionHash(c) }

  const button = { fontSize: 10, padding: '1px 6px' } as const
  const head = (k: SortKey, label: string) => (
    <th>
      <button onClick={() => sortBy(k)} style={{ ...button, border: 'none', background: 'transparent', fontWeight: 'bold' }}
        aria-label={`Sort by ${label}`}>
        {label}{sortKey === k ? (descending ? ' ▼' : ' ▲') : ''}
      </button>
    </th>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
      {error && (
        <div role="alert" style={{ padding: '4px 8px', fontSize: 11, borderRadius: 3,
          background: 'rgba(244,67,54,0.2)', color: 'var(--error)' }}>
          {error}{' '}
          <button style={button} onClick={load}>Retry</button>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <label style={{ fontSize: 11 }}>Show{' '}
          <select aria-label="Filter by mode" value={filter} onChange={e => setFilter(e.target.value as ModeFilter)}>
            <option value="all">All configurations</option>
            <option value={METACAT_MODE}>{METACAT_MODE}</option>
            <option value={TRAINING_MODE}>{TRAINING_MODE}</option>
          </select>
        </label>
        <span className="text-xs text-muted">
          {items ? `${shown.length} of ${items.length} configurations` : 'Loading…'}
          {' '}A change to a configuration takes effect at the start of its next run.
        </span>
      </div>

      {items && (
        <table style={{ borderCollapse: 'collapse', width: '100%' }} aria-label="Configurations">
          <thead>
            <tr style={{ textAlign: 'left' }}>
              {head('name', 'Name')}
              {head('mode', 'Mode')}
              {head('revision', 'Revision')}
              <th>Frozen</th>
              {head('differs', 'Differs from the Metacat Standard Configuration')}
              {head('changed', 'Last change')}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(c => (
              <tr key={c.id} data-testid={`configuration-${c.id}`}
                style={{ background: c.id === openId ? 'var(--bg-panel)' : 'transparent' }}>
                <td>{c.name}</td>
                <td>
                  <span
                    data-testid={`badge-${c.id}`}
                    style={{ background: BADGE_COLORS[badgeMode(c)], borderRadius: 8, padding: '0 6px', fontSize: 11 }}
                  >
                    {badgeText(c)}
                  </span>
                </td>
                <td>{c.revision}</td>
                <td>{c.frozen ? 'frozen' : 'no'}</td>
                <td>
                  {c.differs_from_standard_rows === 0
                    ? 'equals the Metacat Standard Configuration'
                    : `differs from the Metacat Standard Configuration in ${c.differs_from_standard_rows} ${c.differs_from_standard_rows === 1 ? 'row' : 'rows'}`}
                </td>
                <td>{lastChange(c)}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button style={button} aria-label={`Open ${c.name}`} onClick={() => onOpen(c.id)}>Open</button>{' '}
                  <button style={button} aria-label={`Compare ${c.name}`} onClick={() => setCompareFrom(c.id)}>Compare</button>{' '}
                  <button style={button} aria-label={`New session from ${c.name}`} onClick={() => newSession(c)}>
                    New session from this configuration
                  </button>{' '}
                  <button style={button} aria-label={`History of ${c.name}`} onClick={() => onHistory(c.id)}>History</button>{' '}
                  <button style={button} aria-label={`${c.frozen ? 'Unfreeze' : 'Freeze'} ${c.name}`} onClick={() => void toggleFrozen(c)}>
                    {c.frozen ? 'Unfreeze' : 'Freeze'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {items && (
        <ConfigurationCompare
          key={compareFrom ?? 'none'}
          configurations={items}
          initialA={compareFrom ?? undefined}
          initialB={compareFrom === null ? undefined : 'standard'}
          onChanged={() => { setVersion(v => v + 1); onChanged?.() }}
        />
      )}
    </div>
  )
}
