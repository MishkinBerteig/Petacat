import { useState, useEffect, useCallback } from 'react'
import { EditableTable, LoadFailure, type ColumnDef } from './EditableTable'
import { describeApiError, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import { useAdminRequest, type ConfigurationProp } from './adminRequest'

interface DescriptionRule {
  id: number
  rule_key: string
  ordinal: number
  subject: string
  dimension_role: string
  descriptor_source: string
  descriptor_role: string | null
  condition: string
  activate_descriptor: boolean
  built: boolean
  bond_description: boolean
}

interface ActivationRule {
  id: number
  rule_key: string
  ordinal: number
  node_role: string
  condition: string
}

const DESCRIPTION_COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '5%' },
  { key: 'ordinal', label: 'Order', type: 'number', width: '7%' },
  { key: 'rule_key', label: 'Rule', type: 'text', width: '16%' },
  { key: 'subject', label: 'Describes', type: 'text', width: '9%' },
  { key: 'dimension_role', label: 'Description type (node role)', type: 'text', width: '16%' },
  { key: 'descriptor_source', label: 'Descriptor from', type: 'text', width: '9%' },
  { key: 'descriptor_role', label: 'Descriptor (node role)', type: 'text', width: '12%' },
  { key: 'condition', label: 'Condition', type: 'text', width: '8%' },
  { key: 'activate_descriptor', label: 'Activate', type: 'bool', width: '6%' },
  { key: 'built', label: 'Built', type: 'bool', width: '5%' },
  { key: 'bond_description', label: 'Bond description', type: 'bool', width: '6%' },
]

const ACTIVATION_COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', type: 'readonly', width: '6%' },
  { key: 'ordinal', label: 'Order', type: 'number', width: '8%' },
  { key: 'rule_key', label: 'Rule', type: 'text', width: '36%' },
  { key: 'node_role', label: 'Node (role)', type: 'text', width: '28%' },
  { key: 'condition', label: 'Condition', type: 'text', width: '22%' },
]

const DESCRIPTION_ACTIONS = {
  create: 'add the initial description rule',
  update: 'save the initial description rule',
  delete: 'delete the initial description rule',
}

const ACTIVATION_ACTIONS = {
  create: 'add the initial activation rule',
  update: 'save the initial activation rule',
  delete: 'delete the initial activation rule',
}

/** `PUT` carries the whole row, so an edited field is merged into the row it came from. */
function mergedDescription(rows: DescriptionRule[], id: number, patch: Partial<DescriptionRule>) {
  const c = rows.find(r => r.id === id)
  return {
    rule_key: patch.rule_key ?? c?.rule_key ?? '',
    ordinal: patch.ordinal ?? c?.ordinal ?? null,
    subject: patch.subject ?? c?.subject ?? 'letter',
    dimension_role: patch.dimension_role ?? c?.dimension_role ?? '',
    descriptor_source: patch.descriptor_source ?? c?.descriptor_source ?? 'role',
    descriptor_role: patch.descriptor_role !== undefined ? patch.descriptor_role : (c?.descriptor_role ?? null),
    condition: patch.condition ?? c?.condition ?? 'always',
    activate_descriptor: patch.activate_descriptor ?? c?.activate_descriptor ?? true,
    built: patch.built ?? c?.built ?? true,
    bond_description: patch.bond_description ?? c?.bond_description ?? false,
  }
}

function mergedActivation(rows: ActivationRule[], id: number, patch: Partial<ActivationRule>) {
  const c = rows.find(r => r.id === id)
  return {
    rule_key: patch.rule_key ?? c?.rule_key ?? '',
    ordinal: patch.ordinal ?? c?.ordinal ?? null,
    node_role: patch.node_role ?? c?.node_role ?? '',
    condition: patch.condition ?? c?.condition ?? 'always',
  }
}

/**
 * The initial-description program: what a run starts with before the first codelet. Two
 * tables, each applied in order. Each description goes to the front of a letter's list, so
 * the order of the rules is part of what a run does.
 */
export function InitialProgramEditor({ configuration = GLOBAL_CONFIGURATION_ID }: ConfigurationProp) {
  const request = useAdminRequest(configuration)
  const [descriptions, setDescriptions] = useState<DescriptionRule[]>([])
  const [activations, setActivations] = useState<ActivationRule[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(() => {
    Promise.all([
      request<ActivationRule[]>('/admin/initial-activation-rules'),
      request<DescriptionRule[]>('/admin/initial-description-rules'),
    ])
      .then(([acts, descs]) => { setActivations(acts); setDescriptions(descs); setLoadError(null) })
      .catch(e => setLoadError(describeApiError(e, 'load the initial-description program')))
      .finally(() => setLoading(false))
  }, [request])

  useEffect(() => { load() }, [load])
  if (loading) return <div className="text-muted">Loading the initial-description program...</div>
  if (loadError) return <LoadFailure message={loadError} onRetry={load} />

  return (
    <div>
      <div className="text-xs text-muted mb-2">
        What a run starts with, before the first codelet. The concepts below start fully active
        (conditions: always, any_single_letter_string).
      </div>
      <EditableTable
        columns={ACTIVATION_COLUMNS}
        rows={activations}
        idKey="id"
        actions={ACTIVATION_ACTIONS}
        onCreate={async (row) => request<ActivationRule>('/admin/initial-activation-rules', {
          method: 'POST',
          body: JSON.stringify({
            rule_key: row.rule_key ?? '',
            ordinal: row.ordinal ?? null,
            node_role: row.node_role ?? '',
            condition: row.condition ?? 'always',
          }),
        })}
        onUpdate={async (id, row) => request<ActivationRule>(`/admin/initial-activation-rules/${id}`, {
          method: 'PUT',
          body: JSON.stringify(mergedActivation(activations, id as number, row)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/initial-activation-rules/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
      <div className="text-xs text-muted mt-4 mb-2">
        The first descriptions of a structure, applied in order, each at the front of its list. A
        letter (subject letter): conditions always, single, leftmost, rightmost, middle; a translated
        string's letter: always; a new group: always, has_direction, whole, leftmost, middle, rightmost,
        facet_is_letter_category. Descriptor from: role, letter_category or, for a group, group_category,
        bond_category, direction, bond_facet, initial_letter_category.
      </div>
      <EditableTable
        columns={DESCRIPTION_COLUMNS}
        rows={descriptions}
        idKey="id"
        actions={DESCRIPTION_ACTIONS}
        onCreate={async (row) => request<DescriptionRule>('/admin/initial-description-rules', {
          method: 'POST',
          body: JSON.stringify({
            rule_key: row.rule_key ?? '',
            ordinal: row.ordinal ?? null,
            subject: row.subject ?? 'letter',
            dimension_role: row.dimension_role ?? '',
            descriptor_source: row.descriptor_source ?? 'role',
            descriptor_role: row.descriptor_role || null,
            condition: row.condition ?? 'always',
            activate_descriptor: row.activate_descriptor ?? true,
            built: row.built ?? true,
            bond_description: row.bond_description ?? false,
          }),
        })}
        onUpdate={async (id, row) => request<DescriptionRule>(`/admin/initial-description-rules/${id}`, {
          method: 'PUT',
          body: JSON.stringify(mergedDescription(descriptions, id as number, row)),
        })}
        onDelete={async (id) => {
          await request<void>(`/admin/initial-description-rules/${id}`, { method: 'DELETE' })
          return true
        }}
        onRefresh={load}
      />
    </div>
  )
}
