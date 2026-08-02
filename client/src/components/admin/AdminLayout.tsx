import { useState, useRef, useCallback, useEffect } from 'react'
import { request, describeApiError } from '@/api/client'
import { SlipnetEditor } from './SlipnetEditor'
import { CodeletEditor } from './CodeletEditor'
import { ParamsEditor } from './ParamsEditor'
import { DemoEditor } from './DemoEditor'
import { EnumEditor } from './EnumEditor'
import { ThemeDimensionEditor } from './ThemeDimensionEditor'
import { PostingRuleEditor } from './PostingRuleEditor'
import { CommentaryTemplateEditor } from './CommentaryTemplateEditor'
import { SlipnetLayoutEditor } from './SlipnetLayoutEditor'
import { SlipnetLinkEditor } from './SlipnetLinkEditor'
import { HelpTopicEditor } from './HelpTopicEditor'
import { UrgencyLevelEditor } from './UrgencyLevelEditor'
import { FormulaCoefficientEditor } from './FormulaCoefficientEditor'

const TABS = [
  { key: 'slipnet', label: 'Slipnet Nodes' },
  { key: 'links', label: 'Slipnet Links' },
  { key: 'codelets', label: 'Codelet Types' },
  { key: 'params', label: 'Engine Params' },
  { key: 'urgency', label: 'Urgency Levels' },
  { key: 'formulas', label: 'Formula Coefficients' },
  { key: 'demos', label: 'Demo Problems' },
  { key: 'enums', label: 'Enum Tables' },
  { key: 'theme-dims', label: 'Theme Dimensions' },
  { key: 'posting', label: 'Posting Rules' },
  { key: 'commentary', label: 'Commentary Templates' },
  { key: 'layout', label: 'Slipnet Layout' },
  { key: 'help', label: 'Help Topics' },
] as const

type TabKey = typeof TABS[number]['key']

/**
 * What the last configuration-wide action reported.
 *
 * `kind` carries the outcome rather than the wording, so the banner's colour and the
 * sentence a reader sees are decided separately: a failure is red because it failed.
 */
interface Flash {
  kind: 'success' | 'error'
  text: string
}

/**
 * Read a configuration file back in.
 *
 * The file is parsed here, before anything is sent, so a file that is not JSON is named
 * as such. The reply says how many rows each collection carried, and the flash reports
 * that count — what arrived, rather than only that something did.
 */
async function importConfiguration(file: File): Promise<Flash> {
  let data: unknown
  try {
    data = JSON.parse(await file.text())
  } catch {
    return {
      kind: 'error',
      text: `Could not import the configuration: ${file.name} does not contain valid JSON.`,
    }
  }

  try {
    const body = await request<{ imported: Record<string, number> }>('/admin/import', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    const counts = body.imported ?? {}
    const rows = Object.values(counts).reduce((total, n) => total + n, 0)
    return {
      kind: 'success',
      text: `Imported ${rows} rows across ${Object.keys(counts).length} collections — reload tabs to see changes`,
    }
  } catch (err) {
    return { kind: 'error', text: describeApiError(err, 'import the configuration') }
  }
}

interface AdminLayoutProps {
  editNodeName?: string | null;
  onClearEditNode?: () => void;
}

export function AdminLayout({ editNodeName, onClearEditNode }: AdminLayoutProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('slipnet')
  const [flash, setFlash] = useState<Flash | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // A success announces itself and goes; a failure stays until it is read and dismissed.
  useEffect(() => {
    if (flash?.kind !== 'success') return
    const timer = setTimeout(() => setFlash(null), 4000)
    return () => clearTimeout(timer)
  }, [flash])

  // Auto-switch to slipnet tab when editNodeName arrives
  useEffect(() => {
    if (editNodeName) {
      setActiveTab('slipnet');
    }
  }, [editNodeName]);

  /**
   * Download the whole configuration as one JSON file.
   *
   * The file is written from a configuration the server returned. A refusal is reported
   * and nothing is downloaded, so every file that reaches the disk is a backup that can
   * be imported back.
   */
  const handleExport = useCallback(async () => {
    let data: unknown
    try {
      data = await request<unknown>('/admin/export')
    } catch (err) {
      setFlash({ kind: 'error', text: describeApiError(err, 'export the configuration') })
      return
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `petacat-config-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    setFlash({ kind: 'success', text: `Exported the configuration to ${a.download}` })
  }, [])

  /**
   * Write the current configuration out to `seed_data/*.json`.
   *
   * The seed files are what a fresh database is built from and what the repository
   * carries, so this is how a configuration arrived at here becomes the project's own
   * starting point. The response names the files written and the collections whose
   * seed files carry structure the database flattens.
   */
  const handleExportToSeed = useCallback(async () => {
    try {
      const body = await request<{ written: string[]; source_database: string }>(
        '/admin/export-to-seed-data',
        { method: 'POST' },
      )
      setFlash({
        kind: 'success',
        text: `Wrote ${body.written.length} seed files from ${body.source_database}; previous copies kept`,
      })
    } catch (err) {
      setFlash({
        kind: 'error',
        text: describeApiError(err, 'write the current settings to seed data'),
      })
    }
  }, [])

  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFlash(await importConfiguration(file))
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {flash && (
        <div
          role={flash.kind === 'error' ? 'alert' : 'status'}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '4px 8px', fontSize: 11, borderRadius: 3, marginBottom: 2,
            background: flash.kind === 'error' ? 'rgba(244,67,54,0.2)' : 'rgba(76,175,80,0.2)',
            color: flash.kind === 'error' ? 'var(--error)' : 'var(--success)',
          }}
        >
          <span style={{ flex: 1 }}>{flash.text}</span>
          {flash.kind === 'error' && (
            <button onClick={() => setFlash(null)} style={{ fontSize: 10, padding: '1px 6px' }}>
              Dismiss
            </button>
          )}
        </div>
      )}
      <div style={{
        display: 'flex',
        gap: 2,
        padding: '8px 8px 0',
        borderBottom: '1px solid var(--border)',
        flexWrap: 'wrap',
      }}>
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              background: activeTab === tab.key ? 'var(--bg-panel)' : 'transparent',
              borderBottom: activeTab === tab.key ? '2px solid var(--text-accent)' : '2px solid transparent',
              borderRadius: '3px 3px 0 0',
              fontSize: 11,
              padding: '4px 8px',
            }}
          >
            {tab.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button onClick={handleExport} style={{ fontSize: 10, padding: '3px 8px' }}>Export</button>
        <button
          onClick={handleExportToSeed}
          title="Write the current configuration to seed_data/*.json, which a fresh database is built from"
          style={{ fontSize: 10, padding: '3px 8px' }}
        >
          Export Current Settings to Seed Data
        </button>
        <button onClick={() => fileInputRef.current?.click()} style={{ fontSize: 10, padding: '3px 8px' }}>Import</button>
        <input ref={fileInputRef} type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        {activeTab === 'slipnet' && <SlipnetEditor editNodeName={editNodeName} onClearEditNode={onClearEditNode} />}
        {activeTab === 'links' && <SlipnetLinkEditor />}
        {activeTab === 'codelets' && <CodeletEditor />}
        {activeTab === 'params' && <ParamsEditor />}
        {activeTab === 'urgency' && <UrgencyLevelEditor />}
        {activeTab === 'formulas' && <FormulaCoefficientEditor />}
        {activeTab === 'demos' && <DemoEditor />}
        {activeTab === 'enums' && <EnumEditor />}
        {activeTab === 'theme-dims' && <ThemeDimensionEditor />}
        {activeTab === 'posting' && <PostingRuleEditor />}
        {activeTab === 'commentary' && <CommentaryTemplateEditor />}
        {activeTab === 'layout' && <SlipnetLayoutEditor />}
        {activeTab === 'help' && <HelpTopicEditor />}
      </div>
    </div>
  )
}
