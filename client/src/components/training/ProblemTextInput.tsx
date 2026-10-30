// ---------------------------------------------------------------------------
// Petacat -- Trainings: the problems box (text, file upload, preview)
// ---------------------------------------------------------------------------
//
// Used by the new-training form and by "Add problems". The text is parsed live by
// problemText.ts and the preview says what was found, what was rejected and why, and
// how many runs it comes to, before anything is sent.
// ---------------------------------------------------------------------------

import { useRef, useState } from 'react';
import { describeApiError, getDemos } from '@/api/client';
import type { ProblemInput } from '@/types';
import { ControlHelp, fmtInt, labelStyle, noticeStyle } from './shared';
import type { ParsedProblems } from './problemText';

interface InputProps {
  id: string;
  value: string;
  onChange: (text: string) => void;
  disabled?: boolean;
  /** Show the "Add the demo problems" button. */
  demos?: boolean;
  rows?: number;
}

export function ProblemTextInput({ id, value, onChange, disabled, demos = false, rows = 6 }: InputProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const append = (more: string) => {
    onChange(value.trim() === '' ? more : `${value.replace(/\s+$/, '')}\n${more}`);
  };

  const onFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setProblem(null);
      append(String(reader.result ?? ''));
    };
    reader.onerror = () => setProblem(`Could not read ${file.name}.`);
    reader.readAsText(file);
  };

  const addDemos = async () => {
    try {
      const list = await getDemos();
      setProblem(null);
      append(
        list
          .map((d) => `${d.initial} → ${d.modified}; ${d.target} → ${d.answer ? d.answer : '?'}`)
          .join('\n'),
      );
    } catch (err) {
      setProblem(describeApiError(err, 'load the demo problems'));
    }
  };

  return (
    <div>
      <span style={{ display: 'flex', alignItems: 'center' }}>
        <label style={labelStyle} htmlFor={id}>
          Problems
        </label>
        <ControlHelp topic="training_problem_text" label="problem text formats" />
      </span>
      <textarea
        id={id}
        value={value}
        rows={rows}
        disabled={disabled}
        spellCheck={false}
        placeholder={'abc → abd; xyz → ?\nabc -> abd; ijk -> ?\nabc abd xyz wyz'}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: 12, boxSizing: 'border-box' }}
      />
      <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
        <button type="button" disabled={disabled} onClick={() => fileRef.current?.click()}>
          Upload a file…
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.csv,.json,text/plain,text/csv,text/markdown,application/json"
          aria-label="Upload a problems file"
          data-testid={`${id}-file`}
          style={{ display: 'none' }}
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
        {demos && (
          <button type="button" disabled={disabled} onClick={() => void addDemos()}>
            Add the demo problems
          </button>
        )}
        {value !== '' && (
          <button type="button" disabled={disabled} onClick={() => onChange('')}>
            Clear
          </button>
        )}
      </div>
      {problem && (
        <div role="alert" style={{ ...noticeStyle, marginTop: 6 }}>
          {problem}
        </div>
      )}
    </div>
  );
}

/** Total runs the problems come to: each one's own seeds, or the training's default. */
export function totalRuns(problems: ProblemInput[], seedsPerProblem: number): number {
  return problems.reduce((sum, p) => sum + (p.seeds ?? seedsPerProblem), 0);
}

export function ProblemPreview({
  parsed,
  seedsPerProblem,
}: {
  parsed: ParsedProblems;
  seedsPerProblem: number;
}) {
  const { problems, rejected, duplicates } = parsed;
  const [showRejected, setShowRejected] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const runs = totalRuns(problems, seedsPerProblem);
  return (
    <div style={{ marginTop: 6 }} data-testid="problem-preview">
      <div className="text-xs mono" data-testid="preview-summary">
        {fmtInt(problems.length)} problems parsed, {fmtInt(rejected.length)} lines rejected,{' '}
        {fmtInt(duplicates.length)} duplicates
        {problems.length > 0 && <> · {fmtInt(runs)} runs in total</>}
      </div>
      {rejected.length > 0 && (
        <div>
          <button type="button" onClick={() => setShowRejected((v) => !v)} style={toggleStyle}>
            {showRejected ? 'Hide' : 'Show'} rejected lines
          </button>
          {showRejected && (
            <ul style={listStyle} data-testid="rejected-list">
              {rejected.map((r, i) => (
                <li key={i}>
                  <span className="mono">
                    line {r.line}: {r.text}
                  </span>
                  <span style={{ color: 'var(--error)' }}> — {r.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {duplicates.length > 0 && (
        <div>
          <button type="button" onClick={() => setShowDuplicates((v) => !v)} style={toggleStyle}>
            {showDuplicates ? 'Hide' : 'Show'} duplicates
          </button>
          {showDuplicates && (
            <ul style={listStyle} data-testid="duplicate-list">
              {duplicates.map((r, i) => (
                <li key={i} className="mono">
                  line {r.line}: {r.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const toggleStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: 'var(--text-accent)',
  cursor: 'pointer',
  fontSize: 11,
  padding: '2px 0',
};

const listStyle: React.CSSProperties = {
  fontSize: 11,
  margin: '2px 0 0',
  paddingLeft: 16,
  maxHeight: 140,
  overflow: 'auto',
};
