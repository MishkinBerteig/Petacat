import { useState, useRef, useCallback, useEffect } from 'react'
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

interface AdminLayoutProps {
  editNodeName?: string | null;
  onClearEditNode?: () => void;
}

export function AdminLayout({ editNodeName, onClearEditNode }: AdminLayoutProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('slipnet')
  const [flash, setFlash] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-switch to slipnet tab when editNodeName arrives
  useEffect(() => {
    if (editNodeName) {
      setActiveTab('slipnet');
    }
  }, [editNodeName]);

  const handleExport = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/export')
      const data = await res.json()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `petacat-config-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      setFlash('Exported')
    } catch { setFlash('Export failed') }
    setTimeout(() => setFlash(null), 2000)
  }, [])

  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const res = await fetch('/api/admin/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(await res.text())
      setFlash('Imported successfully — reload tabs to see changes')
    } catch (err: any) {
      setFlash(`Import failed: ${err.message}`)
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
    setTimeout(() => setFlash(null), 4000)
  }, [])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {flash && (
        <div style={{
          padding: '4px 8px', fontSize: 11, borderRadius: 3, marginBottom: 2,
          background: flash.includes('fail') ? 'rgba(244,67,54,0.2)' : 'rgba(76,175,80,0.2)',
          color: flash.includes('fail') ? 'var(--error)' : 'var(--success)',
        }}>{flash}</div>
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
