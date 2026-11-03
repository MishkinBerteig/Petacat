import type { ConfigurationSummary } from '@/types/configuration'
import { BADGE_COLORS, badgeMode, chipText, fallbackChipText, sourceLabel } from './configurationLabels'

/**
 * The persistent header chip: which configuration the editors below are changing, and in which
 * mode. It never disappears while an editor is open; before the summary arrives, or if it cannot
 * be loaded, it shows the wording that is true without it.
 *
 * The scope picker (3.10.2) offers only "this configuration" for now.
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
        <select aria-label="Apply to" value="this" onChange={() => {}} style={{ fontSize: 10 }}>
          <option value="this">This configuration</option>
        </select>
      </label>
    </div>
  )
}
