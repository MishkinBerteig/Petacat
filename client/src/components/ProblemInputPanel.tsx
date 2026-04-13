// ---------------------------------------------------------------------------
// ProblemInputPanel — Initial/Modified/Target/Answer inputs + demo dropdown
// ---------------------------------------------------------------------------

import { useState, useEffect, useCallback } from 'react';
import { useRunStore } from '@/store/runStore';
import type { DemoProblem } from '@/types';
import { getDemos } from '@/api/client';

export function ProblemInputPanel() {
  const workspace = useRunStore((s) => s.workspace);
  const formInputs = useRunStore((s) => s.formInputs);
  const setFormInput = useRunStore((s) => s.setFormInput);
  const setFormInputs = useRunStore((s) => s.setFormInputs);
  const status = useRunStore((s) => s.status);
  const isRunning = status === 'running';

  const [demos, setDemos] = useState<DemoProblem[]>([]);
  const [selectedDemo, setSelectedDemo] = useState('');
  const [demosLoading, setDemosLoading] = useState(false);

  // Sync from store when a run is loaded (e.g., via URL hash)
  useEffect(() => {
    if (workspace) {
      setFormInputs({
        initial: workspace.initial,
        modified: workspace.modified,
        target: workspace.target,
        answer: workspace.answer ?? '',
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace]);

  // Fetch demos on mount
  useEffect(() => {
    setDemosLoading(true);
    getDemos()
      .then(setDemos)
      .catch(() => setDemos([]))
      .finally(() => setDemosLoading(false));
  }, []);

  const handleDemoSelect = useCallback(
    (value: string) => {
      setSelectedDemo(value);
      const demo = demos.find((d) => String(d.id) === value);
      if (demo) {
        setFormInputs({
          initial: demo.initial,
          modified: demo.modified,
          target: demo.target,
          answer: demo.answer ?? '',
          seed: String(demo.seed),
        });
      }
    },
    [demos, setFormInputs],
  );

  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: 'var(--text-secondary)',
    marginBottom: 2,
  };

  const fieldGroupStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
    marginBottom: 8,
  };

  return (
    <div className="flex-col" style={{ fontSize: 13 }}>
      <div style={fieldGroupStyle}>
        <label style={labelStyle}>Initial</label>
        <input
          type="text"
          value={formInputs.initial}
          onChange={(e) => setFormInput('initial', e.target.value)}
          placeholder="abc"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle}>Modified</label>
        <input
          type="text"
          value={formInputs.modified}
          onChange={(e) => setFormInput('modified', e.target.value)}
          placeholder="abd"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle}>Target</label>
        <input
          type="text"
          value={formInputs.target}
          onChange={(e) => setFormInput('target', e.target.value)}
          placeholder="xyz"
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle}>Answer (optional)</label>
        <input
          type="text"
          value={formInputs.answer}
          onChange={(e) => setFormInput('answer', e.target.value)}
          placeholder=""
          style={{ width: '100%' }}
          disabled={isRunning}
        />
      </div>

      <div style={fieldGroupStyle}>
        <label style={labelStyle}>Demo Problem</label>
        <select
          value={selectedDemo}
          onChange={(e) => handleDemoSelect(e.target.value)}
          style={{ width: '100%' }}
          disabled={isRunning || demosLoading}
        >
          <option value="">
            {demosLoading ? 'Loading...' : '-- Select Demo --'}
          </option>
          {demos.map((d) => (
            <option key={d.id} value={String(d.id)}>
              {d.name}: {d.initial} -&gt; {d.modified}; {d.target} -&gt; ?
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
