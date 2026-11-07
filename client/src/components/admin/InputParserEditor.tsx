import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { describeApiError, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import { useAdminRequest, type ConfigurationProp } from './adminRequest'

interface CharacterRange {
  id: number
  kind: string
  first: number
  last: number
}

interface LoweringRange {
  id: number
  first: number
  last: number
  step: number
  delta: number
}

const CHARACTER_COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '8%' },
  { key: 'kind', label: 'Kind (alphabetic or numeric)', type: 'text', width: '34%' },
  { key: 'first', label: 'First character (code point)', type: 'number', width: '29%' },
  { key: 'last', label: 'Last character (code point)', type: 'number', width: '29%' },
]

const LOWERING_COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '8%' },
  { key: 'first', label: 'First character (code point)', type: 'number', width: '28%' },
  { key: 'last', label: 'Last character (code point)', type: 'number', width: '28%' },
  { key: 'step', label: 'Step', type: 'number', width: '14%' },
  { key: 'delta', label: 'Lowers by (code points)', type: 'number', width: '22%' },
]

const CHARACTER_ACTIONS = {
  create: 'add the character range',
  update: 'save the character range',
  delete: 'delete the character range',
}

const LOWERING_ACTIONS = {
  create: 'add the lowering range',
  update: 'save the lowering range',
  delete: 'delete the lowering range',
}

/** `PUT` carries the whole row, so an edited field is merged into the row it came from. */
function mergedCharacter(rows: CharacterRange[], id: number, patch: Partial<CharacterRange>) {
  const c = rows.find(r => r.id === id)
  return {
    kind: patch.kind ?? c?.kind ?? '',
    first: Number(patch.first ?? c?.first ?? 0),
    last: Number(patch.last ?? c?.last ?? 0),
  }
}

function mergedLowering(rows: LoweringRange[], id: number, patch: Partial<LoweringRange>) {
  const c = rows.find(r => r.id === id)
  return {
    first: Number(patch.first ?? c?.first ?? 0),
    last: Number(patch.last ?? c?.last ?? 0),
    step: Number(patch.step ?? c?.step ?? 1),
    delta: Number(patch.delta ?? c?.delta ?? 0),
  }
}

/**
 * Metacat's input parser, which Metacat Mode reads every problem through (and Training Mode
 * does not). The rules are data: which characters are letters or digits, and how each is
 * lowered. The readable letters are the Slipnet's letter nodes, and the largest seed is the
 * engine parameter `largest_seed`; neither is edited here.
 */
export function InputParserEditor({ configuration = GLOBAL_CONFIGURATION_ID }: ConfigurationProp) {
  const request = useAdminRequest(configuration)
  const [characters, setCharacters] = useState<CharacterRange[]>([])
  const [lowering, setLowering] = useState<LoweringRange[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(() => {
    Promise.all([
      request<CharacterRange[]>('/admin/input-character-ranges'),
      request<LoweringRange[]>('/admin/input-lowering-ranges'),
    ])
      .then(([chars, lows]) => { setCharacters(chars); setLowering(lows); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the input parser')))
      .finally(() => setLoading(false))
  }, [request])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading the input parser...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        Metacat Mode reads each problem through Metacat's input parser: the fields are one line, a
        letter or a digit belongs to a string or a number, and any other character separates them.
        A character in a row below is alphabetic or numeric (Unicode code points, inclusive); any
        other character is a separator. A Training Mode Session does not use these rows.
      </div>
      <EditableTable
        columns={CHARACTER_COLUMNS}
        rows={characters}
        idKey="id"
        actions={CHARACTER_ACTIONS}
        onCreate={async (row) => request<CharacterRange>('/admin/input-character-ranges', {
          method: 'POST',
          body: JSON.stringify({
            kind: row.kind ?? '',
            first: Number(row.first ?? 0),
            last: Number(row.last ?? 0),
          }),
        })}
        onUpdate={async (id, row) => request<CharacterRange>(`/admin/input-character-ranges/${id}`, {
          method: 'PUT',
          body: JSON.stringify(mergedCharacter(characters, id as number, row)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/input-character-ranges/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
      <div className="text-xs text-muted mt-4 mb-2">
        Lowering: the characters first, first + step, ... up to last each become the character
        "lowers by" further on. A character in no row is its own lowered form.
      </div>
      <EditableTable
        columns={LOWERING_COLUMNS}
        rows={lowering}
        idKey="id"
        actions={LOWERING_ACTIONS}
        onCreate={async (row) => request<LoweringRange>('/admin/input-lowering-ranges', {
          method: 'POST',
          body: JSON.stringify({
            first: Number(row.first ?? 0),
            last: Number(row.last ?? 0),
            step: Number(row.step ?? 1),
            delta: Number(row.delta ?? 0),
          }),
        })}
        onUpdate={async (id, row) => request<LoweringRange>(`/admin/input-lowering-ranges/${id}`, {
          method: 'PUT',
          body: JSON.stringify(mergedLowering(lowering, id as number, row)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/input-lowering-ranges/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
