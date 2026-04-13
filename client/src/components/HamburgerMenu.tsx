import { useState, useEffect, useRef } from 'react'

export type AppView = 'dashboard' | 'config' | 'admin'

interface Props {
  activeView: AppView
  onSelect: (view: AppView) => void
  disabled?: boolean
}

export function HamburgerMenu({ activeView, onSelect, disabled }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const select = (view: AppView) => {
    onSelect(view)
    setOpen(false)
  }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        title="Menu"
        aria-label="Navigation menu"
        style={{
          background: 'none',
          border: '1px solid var(--border, #444)',
          borderRadius: 4,
          color: 'var(--text-primary, #ddd)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          fontSize: 16,
          lineHeight: 1,
          padding: '2px 7px',
          fontFamily: 'var(--font-mono)',
          marginRight: 10,
          opacity: disabled ? 0.4 : 1,
        }}
      >
        &#9776;
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            background: 'var(--bg-panel, #1e1e1e)',
            border: '1px solid var(--border, #444)',
            borderRadius: 4,
            minWidth: 180,
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          <MenuItem
            label="Run Dashboard"
            active={activeView === 'dashboard'}
            onClick={() => select('dashboard')}
          />
          <MenuItem
            label="Configuration"
            active={activeView === 'config'}
            onClick={() => select('config')}
          />
          <MenuItem
            label="Admin"
            active={activeView === 'admin'}
            onClick={() => select('admin')}
          />
        </div>
      )}
    </div>
  )
}

function MenuItem({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: active ? 'var(--bg-highlight, #2a2a2a)' : 'transparent',
        border: 'none',
        borderBottom: '1px solid var(--border, #333)',
        color: 'var(--text-primary, #ddd)',
        fontWeight: active ? 700 : 400,
        cursor: 'pointer',
        padding: '8px 12px',
        fontSize: 13,
        fontFamily: 'inherit',
      }}
    >
      {active && <span style={{ marginRight: 6 }}>&#10003;</span>}
      {label}
    </button>
  )
}
