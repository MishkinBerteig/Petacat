import { useState, useRef, useCallback, useEffect } from 'react'
import { request, describeApiError, getConfigurationSummary, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import type { ConfigurationSummary } from '@/types/configuration'
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
import { ConfigurationPanel } from './ConfigurationPanel'
import { ConfigurationBanner } from './ConfigurationBanner'
import { DatabasePanel } from './database/DatabasePanel'
import { HistoryPanel } from './history/HistoryPanel'
import { ConfigurationChip } from './ConfigurationChip'
import { ConfigurationsTab } from './ConfigurationsTab'
import { isChangingState } from './configurationLabels'
import { ScopeProvider } from './editScope'

const TABS = [
  { key: 'configurations', label: 'Configurations' },
  { key: 'configuration', label: 'Status and reset' },
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
  { key: 'history', label: 'History' },
  { key: 'database', label: 'Database (all modes)' },
] as const

/** The tabs that show the configuration manager itself rather than edit the open configuration. */
const MANAGER_TABS: readonly string[] = ['configurations']

/** The tabs that belong to the global configuration only: the engine's vocabulary and content. */
const GLOBAL_ONLY_TABS: readonly string[] = ['enums', 'help']

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

/**
 * The configuration a link asks the Admin view to open: `#/admin?configuration=<id>` (the
 * Training Mode Session's Configuration tab links here). Anything else is no request.
 */
export function configurationFromHash(): number | null {
  const match = window.location.hash.match(/^#\/admin\?(.*)$/)
  if (!match) return null
  const raw = new URLSearchParams(match[1]).get('configuration')
  if (raw === null || !/^\d+$/.test(raw)) return null
  const id = Number(raw)
  return id >= 1 ? id : null
}

interface AdminLayoutProps {
  editNodeName?: string | null;
  onClearEditNode?: () => void;
}

export function AdminLayout({ editNodeName, onClearEditNode }: AdminLayoutProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('slipnet')
  const [flash, setFlash] = useState<Flash | null>(null)
  const [configurationChanges, setConfigurationChanges] = useState(0)
  // The configuration the editors below are changing; 1 is the global one (Metacat Mode).
  const [openId, setOpenId] = useState(() => configurationFromHash() ?? GLOBAL_CONFIGURATION_ID)
  const [summary, setSummary] = useState<ConfigurationSummary | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // A success announces itself and goes; a failure stays until it is read and dismissed.
  useEffect(() => {
    if (flash?.kind !== 'success') return
    const timer = setTimeout(() => setFlash(null), 4000)
    return () => clearTimeout(timer)
  }, [flash])

  // What the header chip says is the open configuration's own summary; if it cannot be read the
  // chip falls back to wording that is true without it.
  useEffect(() => {
    let live = true
    setSummary(null)
    getConfigurationSummary(openId)
      .then(s => { if (live) setSummary(s) })
      .catch(() => { if (live) setSummary(null) })
    return () => { live = false }
  }, [openId, configurationChanges, activeTab])

  const bump = useCallback(() => setConfigurationChanges(n => n + 1), [])

  /** Open a configuration in the editors (the Slipnet Nodes tab). */
  const open = useCallback((id: number, tab: TabKey = 'slipnet') => {
    setOpenId(id)
    setActiveTab(tab)
  }, [])

  // A link to `#/admin?configuration=<id>` opens that configuration, also while this view is shown.
  useEffect(() => {
    const onHash = () => {
      const id = configurationFromHash()
      if (id !== null) open(id)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [open])

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

  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFlash(await importConfiguration(file))
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  return (
    <ScopeProvider openId={openId}>
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
      {!MANAGER_TABS.includes(activeTab) && <ConfigurationBanner configuration={openId} refreshKey={`${activeTab}:${configurationChanges}`} />}
      {!MANAGER_TABS.includes(activeTab) && <ConfigurationChip configuration={openId} summary={summary} />}
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
        <button onClick={() => fileInputRef.current?.click()} style={{ fontSize: 10, padding: '3px 8px' }}>Import</button>
        <input ref={fileInputRef} type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        {activeTab === 'configurations' && (
          <ConfigurationsTab
            openId={openId}
            onOpen={id => open(id)}
            onHistory={id => open(id, 'history')}
            onChanged={bump}
            refreshKey={configurationChanges}
          />
        )}
        {activeTab !== 'configurations' && summary && isChangingState(summary) && (
          <div role="status" data-testid="changing-state">
            This session is changing state ({summary.session_state}); its configuration is read-only until it has finished.
          </div>
        )}
        {activeTab !== 'configurations' && !(summary && isChangingState(summary)) && (
          GLOBAL_ONLY_TABS.includes(activeTab) && openId !== GLOBAL_CONFIGURATION_ID ? (
            <div role="status" data-testid="global-only">
              {activeTab === 'enums'
                ? "The enum tables are the engine's vocabulary, and only the global configuration (Metacat Mode) has them."
                : 'Help topics are content shared by every mode, not part of a configuration. Open the global configuration to edit them.'}
            </div>
          ) : (
            <>
              {activeTab === 'configuration' && (
                <ConfigurationPanel
                  onChanged={bump}
                  configuration={openId}
                  modeLabel={summary?.mode_label ?? (openId === GLOBAL_CONFIGURATION_ID ? 'Metacat Mode' : 'Training Mode')}
                />
              )}
              {activeTab === 'slipnet' && <SlipnetEditor configuration={openId} editNodeName={editNodeName} onClearEditNode={onClearEditNode} />}
              {activeTab === 'links' && <SlipnetLinkEditor configuration={openId} />}
              {activeTab === 'codelets' && <CodeletEditor configuration={openId} />}
              {activeTab === 'params' && <ParamsEditor configuration={openId} />}
              {activeTab === 'urgency' && <UrgencyLevelEditor configuration={openId} />}
              {activeTab === 'formulas' && <FormulaCoefficientEditor configuration={openId} />}
              {activeTab === 'demos' && <DemoEditor configuration={openId} />}
              {activeTab === 'enums' && <EnumEditor />}
              {activeTab === 'theme-dims' && <ThemeDimensionEditor configuration={openId} />}
              {activeTab === 'posting' && <PostingRuleEditor configuration={openId} />}
              {activeTab === 'commentary' && <CommentaryTemplateEditor configuration={openId} />}
              {activeTab === 'layout' && <SlipnetLayoutEditor configuration={openId} />}
              {activeTab === 'help' && <HelpTopicEditor />}
              {activeTab === 'history' && (
                <div data-testid="history-slot">
                  <HistoryPanel configurationId={openId} onChanged={() => setConfigurationChanges(n => n + 1)} />
                </div>
              )}
              {activeTab === 'database' && <DatabasePanel />}
            </>
          )
        )}
      </div>
    </div>
    </ScopeProvider>
  )
}
