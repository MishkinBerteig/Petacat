import { useState } from 'react'
import { request } from '@/api/client'
import { describeDbError } from './errors'
import type { SqlResult } from './types'
import { showValue } from './values'

/**
 * A read-only SQL box: one SELECT or WITH statement, run by the server in a read-only
 * transaction with a row limit and a timeout. It shows the database, so a Training Mode
 * Session's rows are stored rows, not a running session's current state.
 */
export function SqlBox() {
  const [sql, setSql] = useState('SELECT name, value FROM engine_params ORDER BY name LIMIT 20')
  const [result, setResult] = useState<SqlResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    try {
      setResult(await request<SqlResult>('/admin/db/sql', { method: 'POST', body: JSON.stringify({ sql }) }))
      setError(null)
    } catch (err) {
      setResult(null)
      setError(describeDbError(err, 'run the statement'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="SQL box" style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600 }}>SQL (read-only)</div>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginBottom: 4 }}>
        One SELECT or WITH statement, in a read-only transaction, with a row limit and a timeout.
        It shows the stored database.
      </div>
      <textarea
        aria-label="SQL statement"
        value={sql}
        rows={4}
        onChange={e => setSql(e.target.value)}
        style={{ width: '100%', fontFamily: 'var(--font-mono, monospace)', fontSize: 11 }}
      />
      <button onClick={run} disabled={busy} style={{ fontSize: 11 }}>Run</button>
      {error && <div role="alert" style={{ color: 'var(--error)', fontSize: 11, marginTop: 4 }}>{error}</div>}
      {result && (
        <div style={{ marginTop: 4, overflow: 'auto' }}>
          <div style={{ fontSize: 10 }}>
            {result.row_count} row{result.row_count === 1 ? '' : 's'}
            {result.truncated ? ` (limited to the first ${result.limit})` : ''}
          </div>
          <table style={{ fontSize: 11, borderCollapse: 'collapse' }}>
            <thead>
              <tr>{result.columns.map((c, i) => <th key={i} style={cell}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((r, i) => (
                <tr key={i}>{r.map((v, j) => <td key={j} style={cell}>{showValue(v)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

const cell = { border: '1px solid var(--border)', padding: '2px 6px', textAlign: 'left' as const }
