// ---------------------------------------------------------------------------
// EditableTable — Reusable inline-editing table for admin config tabs
// ---------------------------------------------------------------------------

import { useState, useCallback, useRef, useEffect } from 'react';

export interface ColumnDef {
  key: string;
  label: string;
  type: 'text' | 'number' | 'readonly';
  width?: string;
}

interface Props<T extends Record<string, any>> {
  columns: ColumnDef[];
  rows: T[];
  idKey: string;
  onCreate?: (row: Partial<T>) => Promise<T | null>;
  onUpdate?: (id: any, row: Partial<T>) => Promise<T | null>;
  onDelete?: (id: any) => Promise<boolean>;
  onRefresh?: () => void;
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
  highlightId,
  highlightRef,
}: Props<T>) {
  const [editingCell, setEditingCell] = useState<{ id: any; key: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [newRow, setNewRow] = useState<Record<string, string> | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<any>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingCell && inputRef.current) inputRef.current.focus();
  }, [editingCell]);

  useEffect(() => {
    if (flash) {
      const t = setTimeout(() => setFlash(null), 2000);
      return () => clearTimeout(t);
    }
  }, [flash]);

  const startEdit = (id: any, key: string, value: any) => {
    setEditingCell({ id, key });
    setEditValue(String(value ?? ''));
  };

  const saveEdit = useCallback(async () => {
    if (!editingCell || !onUpdate) return;
    const col = columns.find(c => c.key === editingCell.key);
    const parsed = col?.type === 'number' ? Number(editValue) : editValue;
    try {
      await onUpdate(editingCell.id, { [editingCell.key]: parsed } as Partial<T>);
      setFlash({ id: editingCell.id, type: 'success', message: 'Saved' });
      onRefresh?.();
    } catch (e: any) {
      setFlash({ id: editingCell.id, type: 'error', message: e.message ?? 'Error' });
    }
    setEditingCell(null);
  }, [editingCell, editValue, columns, onUpdate, onRefresh]);

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
    const parsed: any = {};
    for (const col of columns) {
      parsed[col.key] = col.type === 'number' ? Number(newRow[col.key] || 0) : newRow[col.key];
    }
    try {
      await onCreate(parsed);
      setNewRow(null);
      setFlash({ id: '__new__', type: 'success', message: 'Created' });
      onRefresh?.();
    } catch (e: any) {
      setFlash({ id: '__new__', type: 'error', message: e.message ?? 'Error' });
    }
  }, [newRow, columns, onCreate, onRefresh]);

  const handleDelete = useCallback(async (id: any) => {
    if (!onDelete) return;
    try {
      await onDelete(id);
      setConfirmDelete(null);
      setFlash({ id, type: 'success', message: 'Deleted' });
      onRefresh?.();
    } catch (e: any) {
      setConfirmDelete(null);
      setFlash({ id, type: 'error', message: e.message ?? 'Cannot delete' });
    }
  }, [onDelete, onRefresh]);

  const cellPad = '3px 8px';
  const thStyle = { textAlign: 'left' as const, padding: '4px 8px', fontSize: 11 };

  return (
    <div>
      {flash && (
        <div style={{
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
                    : flash?.id === id
                      ? flash.type === 'success' ? 'rgba(76,175,80,0.1)' : 'rgba(244,67,54,0.1)'
                      : undefined,
                  outline: isHighlighted ? '2px solid var(--text-accent)' : undefined,
                  transition: 'background 0.3s, outline 0.3s',
                }}
              >
                {columns.map(col => {
                  const isEditing = editingCell?.id === id && editingCell.key === col.key;
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
                      onDoubleClick={canEdit ? () => startEdit(id, col.key, row[col.key]) : undefined}
                      title={canEdit ? 'Double-click to edit' : undefined}
                    >
                      {String(row[col.key] ?? '')}
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
                  <input
                    value={newRow[col.key] ?? ''}
                    onChange={e => setNewRow(r => r ? { ...r, [col.key]: e.target.value } : r)}
                    type={col.type === 'number' ? 'number' : 'text'}
                    placeholder={col.label}
                    style={{ width: '100%', fontSize: 11, padding: '1px 4px' }}
                    onKeyDown={e => { if (e.key === 'Enter') saveNewRow(); if (e.key === 'Escape') setNewRow(null); }}
                  />
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
