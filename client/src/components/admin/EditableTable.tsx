// ---------------------------------------------------------------------------
// EditableTable — Reusable inline-editing table for admin config tabs
// ---------------------------------------------------------------------------

import { useState, useCallback, useRef, useEffect } from 'react';

import { describeApiError } from '@/api/client';

export interface ColumnDef {
  key: string;
  label: string;
  /**
   * `json` holds a list or object: the cell shows it as JSON and the edit box takes
   * JSON back, so a column like `valid_relations` or `template_data` is editable in
   * the same table as the scalar ones.
   */
  type: 'text' | 'number' | 'readonly' | 'json';
  width?: string;
  /**
   * A `number` column whose value may be absent. An empty box submits `null` for a
   * nullable column and `0` for the rest, so a column that carries a real zero and a
   * column that carries "no value" each say what they mean.
   */
  nullable?: boolean;
}

/**
 * What a collection shows in place of itself when the list could not be loaded.
 *
 * A tab whose load failed says why and offers the retry, rather than holding "Loading..."
 * for as long as the reader is willing to wait.
 */
export function LoadFailure({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert" style={{ fontSize: 12, color: 'var(--error)' }}>
      <div>{message}</div>
      <button onClick={onRetry} style={{ fontSize: 10, marginTop: 6 }}>
        Retry
      </button>
    </div>
  );
}

/** What a cell shows: JSON columns as JSON, everything else as its own text. */
function displayValue(col: ColumnDef, value: any): string {
  if (value === null || value === undefined) return '';
  return col.type === 'json' ? JSON.stringify(value) : String(value);
}

/**
 * What a cell submits. A number column reports an empty box as `null` — the absence of a
 * value — which keeps it distinct from `0`, a number a field like a slipnet link's length
 * genuinely takes. A JSON column reports its own parse error.
 */
function parseValue(col: ColumnDef, raw: string): any {
  if (col.type === 'number') {
    return raw.trim() === '' ? (col.nullable ? null : 0) : Number(raw);
  }
  if (col.type !== 'json') return raw;
  const text = raw.trim();
  if (text === '') return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${col.label} needs valid JSON`);
  }
}

/**
 * What each operation is, in the words the reader would use for it.
 *
 * A failure is reported against the phrase for the operation that failed, so the table
 * says "Could not delete the posting rule" rather than naming a row in the abstract. Each
 * editor names its own collection here.
 */
export interface TableActions {
  create?: string;
  update?: string;
  delete?: string;
}

const GENERIC_ACTIONS: Required<TableActions> = {
  create: 'add the row',
  update: 'save the change',
  delete: 'delete the row',
};

interface Props<T extends Record<string, any>> {
  columns: ColumnDef[];
  rows: T[];
  idKey: string;
  onCreate?: (row: Partial<T>) => Promise<T | null>;
  onUpdate?: (id: any, row: Partial<T>) => Promise<T | null>;
  onDelete?: (id: any) => Promise<boolean>;
  onRefresh?: () => void;
  /** The three operation phrases this table's editor names its collection with. */
  actions?: TableActions;
  highlightId?: string | null;
  highlightRef?: React.Ref<HTMLTableRowElement>;
}

interface Flash {
  id: any;
  type: 'success' | 'error';
  message: string;
}

export function EditableTable<T extends Record<string, any>>({
  columns,
  rows,
  idKey,
  onCreate,
  onUpdate,
  onDelete,
  onRefresh,
  actions,
  highlightId,
  highlightRef,
}: Props<T>) {
  const [editingCell, setEditingCell] = useState<{ id: any; key: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [newRow, setNewRow] = useState<Record<string, string> | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<any>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const createAction = actions?.create ?? GENERIC_ACTIONS.create;
  const updateAction = actions?.update ?? GENERIC_ACTIONS.update;
  const deleteAction = actions?.delete ?? GENERIC_ACTIONS.delete;

  useEffect(() => {
    if (editingCell && inputRef.current) inputRef.current.focus();
  }, [editingCell]);

  // A success announces itself and gets out of the way; a failure stays on screen until
  // the next operation replaces it, so the reader has as long as they need with it.
  useEffect(() => {
    if (flash && flash.type === 'success') {
      const t = setTimeout(() => setFlash(null), 2000);
      return () => clearTimeout(t);
    }
  }, [flash]);

  const startEdit = (id: any, col: ColumnDef, value: any) => {
    setEditingCell({ id, key: col.key });
    setEditValue(displayValue(col, value));
  };

  const saveEdit = useCallback(async () => {
    if (!editingCell || !onUpdate) return;
    const col = columns.find(c => c.key === editingCell.key);
    try {
      const parsed = col ? parseValue(col, editValue) : editValue;
      await onUpdate(editingCell.id, { [editingCell.key]: parsed } as Partial<T>);
      setFlash({ id: editingCell.id, type: 'success', message: 'Saved' });
      onRefresh?.();
    } catch (e) {
      setFlash({
        id: editingCell.id,
        type: 'error',
        message: describeApiError(e, updateAction),
      });
    }
    setEditingCell(null);
  }, [editingCell, editValue, columns, onUpdate, onRefresh, updateAction]);

  const cancelEdit = () => setEditingCell(null);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveEdit();
    if (e.key === 'Escape') cancelEdit();
  };

  const startNewRow = () => {
    const empty: Record<string, string> = {};
    for (const col of columns) empty[col.key] = '';
    setNewRow(empty);
  };

  const saveNewRow = useCallback(async () => {
    if (!newRow || !onCreate) return;
    try {
      const parsed: any = {};
      for (const col of columns) {
        if (col.type === 'readonly') continue;
        parsed[col.key] = parseValue(col, newRow[col.key] ?? '');
      }
      await onCreate(parsed);
      setNewRow(null);
      setFlash({ id: '__new__', type: 'success', message: 'Created' });
      onRefresh?.();
    } catch (e) {
      // The typed row stays on screen with the message, so a rejected value is corrected
      // rather than retyped.
      setFlash({ id: '__new__', type: 'error', message: describeApiError(e, createAction) });
    }
  }, [newRow, columns, onCreate, onRefresh, createAction]);

  const handleDelete = useCallback(async (id: any) => {
    if (!onDelete) return;
    try {
      await onDelete(id);
      setConfirmDelete(null);
      setFlash({ id, type: 'success', message: 'Deleted' });
      onRefresh?.();
    } catch (e) {
      // The row survives a refused delete: it is still there on the server, and the
      // table goes on showing it alongside the reason it is still there.
      setConfirmDelete(null);
      setFlash({ id, type: 'error', message: describeApiError(e, deleteAction) });
    }
  }, [onDelete, onRefresh, deleteAction]);

  const cellPad = '3px 8px';
  const thStyle = { textAlign: 'left' as const, padding: '4px 8px', fontSize: 11 };

  return (
    <div>
      {flash && (
        <div role={flash.type === 'error' ? 'alert' : 'status'} style={{
          padding: '4px 8px',
          marginBottom: 4,
          fontSize: 11,
          borderRadius: 3,
          background: flash.type === 'success' ? 'rgba(76,175,80,0.2)' : 'rgba(244,67,54,0.2)',
          color: flash.type === 'success' ? 'var(--success)' : 'var(--error)',
        }}>
          {flash.message}
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {columns.map(col => (
              <th key={col.key} style={{ ...thStyle, width: col.width }}>
                {col.label}
              </th>
            ))}
            {onDelete && <th style={{ ...thStyle, width: '30px' }}></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const id = row[idKey];
            const isHighlighted = highlightId != null && String(id) === String(highlightId);
            return (
              <tr
                key={String(id)}
                ref={isHighlighted ? highlightRef : undefined}
                style={{
                  borderBottom: '1px solid var(--border)',
                  background: isHighlighted
                    ? 'rgba(0,212,255,0.15)'
                    : flash && flash.id === id
                      ? flash.type === 'success' ? 'rgba(76,175,80,0.1)' : 'rgba(244,67,54,0.1)'
                      : undefined,
                  outline: isHighlighted ? '2px solid var(--text-accent)' : undefined,
                  transition: 'background 0.3s, outline 0.3s',
                }}
              >
                {columns.map(col => {
                  const isEditing =
                    editingCell !== null && editingCell.id === id && editingCell.key === col.key;
                  const canEdit = col.type !== 'readonly' && onUpdate;

                  if (isEditing) {
                    return (
                      <td key={col.key} style={{ padding: cellPad }}>
                        <input
                          ref={inputRef}
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={saveEdit}
                          onKeyDown={handleKeyDown}
                          type={col.type === 'number' ? 'number' : 'text'}
                          style={{ width: '100%', fontSize: 11, padding: '1px 4px' }}
                        />
                      </td>
                    );
                  }

                  return (
                    <td
                      key={col.key}
                      className="mono text-xs"
                      style={{
                        padding: cellPad,
                        cursor: canEdit ? 'pointer' : undefined,
                      }}
                      onDoubleClick={canEdit ? () => startEdit(id, col, row[col.key]) : undefined}
                      title={canEdit ? 'Double-click to edit' : undefined}
                    >
                      {displayValue(col, row[col.key])}
                    </td>
                  );
                })}
                {onDelete && (
                  <td style={{ padding: cellPad, textAlign: 'center' }}>
                    {confirmDelete === id ? (
                      <span style={{ fontSize: 10 }}>
                        <button onClick={() => handleDelete(id)} style={{ fontSize: 10, padding: '0 4px', color: 'var(--error)' }}>Yes</button>
                        <button onClick={() => setConfirmDelete(null)} style={{ fontSize: 10, padding: '0 4px' }}>No</button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(id)}
                        style={{ fontSize: 10, padding: '0 4px', background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
                        title="Delete"
                      >
                        &#x2715;
                      </button>
                    )}
                  </td>
                )}
              </tr>
            );
          })}

          {/* New row input */}
          {newRow && (
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'rgba(0,212,255,0.05)' }}>
              {columns.map(col => (
                <td key={col.key} style={{ padding: cellPad }}>
                  {/* A readonly column is assigned by the server — an id from its own
                      sequence — so the new row leaves it blank. */}
                  {col.type !== 'readonly' && (
                    <input
                      value={newRow[col.key] ?? ''}
                      onChange={e => setNewRow(r => r ? { ...r, [col.key]: e.target.value } : r)}
                      type={col.type === 'number' ? 'number' : 'text'}
                      placeholder={col.label}
                      aria-label={col.label}
                      style={{ width: '100%', fontSize: 11, padding: '1px 4px' }}
                      onKeyDown={e => { if (e.key === 'Enter') saveNewRow(); if (e.key === 'Escape') setNewRow(null); }}
                    />
                  )}
                </td>
              ))}
              {onDelete && <td></td>}
            </tr>
          )}
        </tbody>
      </table>

      <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
        {onCreate && !newRow && (
          <button onClick={startNewRow} style={{ fontSize: 10 }}>+ Add</button>
        )}
        {newRow && (
          <>
            <button onClick={saveNewRow} style={{ fontSize: 10 }} className="primary">Save</button>
            <button onClick={() => setNewRow(null)} style={{ fontSize: 10 }}>Cancel</button>
          </>
        )}
      </div>
    </div>
  );
}
