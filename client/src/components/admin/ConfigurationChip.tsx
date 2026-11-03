import type { ConfigurationSummary } from '@/types/configuration'
import { useScope } from './editScope'
import { ControlHelp } from '../session/shared'
import { BADGE_COLORS, badgeMode, chipText, fallbackChipText, sourceLabel } from './configurationLabels'

/**
 * The persistent header chip: which configuration the editors below are changing, and in which
 * mode. It never disappears while an editor is open; before the summary arrives, or if it cannot
 * be loaded, it shows the wording that is true without it.
 *
 * The scope picker (3.10.2): "this configuration" (the default), "chosen configurations" (a
 * checklist) or "all configurations" (every one not frozen). Anything but the first sends a save
 * through the preview. Without a `ScopeProvider` only "this configuration" is offered.
 */
export function ConfigurationChip({
  configuration,
  summary,
}: {
  configuration: number
  summary: ConfigurationSummary | null
}) {
  const text = summary ? chipText(summary) : fallbackChipText(configuration)
  const mode = summary ? badgeMode(summary) : configuration === 1 ? 'Metacat Mode' : 'Training Mode'
  const label = summary ? sourceLabel(summary) : null
  const sc = useScope()
  const pick = sc?.scope.mode ?? 'this'
  const toggle = (id: number) => {
    if (!sc) return
    const ids = sc.scope.ids.includes(id) ? sc.scope.ids.filter(i => i !== id) : [...sc.scope.ids, id]
    sc.setScope({ mode: 'chosen', ids })
  }
  return (
    <div
      role="note"
      aria-label="Configuration being edited"
      data-testid="configuration-chip"
      style={{
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        padding: '3px 8px', fontSize: 11, marginBottom: 2, borderRadius: 3,
        background: BADGE_COLORS[mode], color: 'var(--text-primary)',
      }}
    >
      <span style={{ flex: 1 }}>{text}</span>
      {label && (
        <span
          data-testid="source-label"
          style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '0 6px', fontSize: 10 }}
        >
          {label}
        </span>
      )}
      <label style={{ fontSize: 10 }}>
        Apply to{' '}
        <select
          aria-label="Apply to" value={pick} style={{ fontSize: 10 }}
          onChange={e => sc?.setScope({ mode: e.target.value as 'this' | 'chosen' | 'all', ids: sc.scope.ids })}
        >
          <option value="this">This configuration</option>
          {sc && <option value="chosen">Chosen configurations</option>}
          {sc && <option value="all">All configurations</option>}
        </select>
      </label>
      <ControlHelp topic="edit_scope" label="the scope picker (Apply to)" />
      {sc && pick === 'all' && (
        <span data-testid="scope-all-note" style={{ fontSize: 10 }}>
          Every configuration that is not frozen; frozen ones are skipped and listed in the preview.
        </span>
      )}
      {sc && pick === 'chosen' && (
        <fieldset aria-label="Chosen configurations" style={{ flexBasis: '100%', border: 'none', padding: 0, margin: 0, fontSize: 10 }}>
          {(sc.configurations ?? []).map(c => (
            <label key={c.id} style={{ marginRight: 10, whiteSpace: 'nowrap' }}>
              <input
                type="checkbox" aria-label={`Include ${c.name}`}
                checked={sc.scope.ids.includes(c.id)} onChange={() => toggle(c.id)}
              />{' '}
              {c.name}{c.frozen ? ' (frozen)' : ''}
            </label>
          ))}
          {sc.configurations === null && 'Loading the configurations...'}
        </fieldset>
      )}
    </div>
  )
}
