// ---------------------------------------------------------------------------
// Petacat -- Training: the error policy fields ("When things go wrong")
// ---------------------------------------------------------------------------
//
// Shared by the new-Training form and by the detail view, where the policy stays
// editable after creation (the settings do not).
// ---------------------------------------------------------------------------

import type { TrainingErrorPolicy } from '@/types';
import { fieldGroupStyle, labelStyle } from './shared';

export const FALLBACK_POLICY: TrainingErrorPolicy = {
  on_run_error: 'record',
  max_errors_per_problem: null,
  max_errors_total: null,
  on_worker_failure: 'retry',
  max_retries: 3,
  on_config_change: 'pause',
};

function numOrNull(text: string): number | null {
  const n = Number(text);
  return text.trim() === '' || !Number.isFinite(n) ? null : Math.max(0, Math.floor(n));
}

interface Props {
  idPrefix: string;
  policy: TrainingErrorPolicy;
  onChange: (policy: TrainingErrorPolicy) => void;
  disabled?: boolean;
}

export function PolicyFields({ idPrefix, policy, onChange, disabled }: Props) {
  const set = (patch: Partial<TrainingErrorPolicy>) => onChange({ ...policy, ...patch });
  const id = (n: string) => `${idPrefix}-${n}`;
  return (
    <div data-testid={`${idPrefix}-fields`}>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor={id('on-run-error')}>
            When a run raises an error
          </label>
          <select
            id={id('on-run-error')}
            value={policy.on_run_error}
            disabled={disabled}
            onChange={(e) => set({ on_run_error: e.target.value as TrainingErrorPolicy['on_run_error'] })}
          >
            <option value="record">Record the error and carry on</option>
            <option value="skip_problem">Skip the rest of that problem</option>
            <option value="pause">Pause the Training</option>
            <option value="cancel">Cancel the Training</option>
          </select>
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor={id('max-per-problem')}>
            Max errors per problem
          </label>
          <input
            id={id('max-per-problem')}
            type="number"
            min={0}
            placeholder="no limit"
            value={policy.max_errors_per_problem ?? ''}
            disabled={disabled}
            onChange={(e) => set({ max_errors_per_problem: numOrNull(e.target.value) })}
            style={{ width: 90 }}
          />
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor={id('max-total')}>
            Max errors total
          </label>
          <input
            id={id('max-total')}
            type="number"
            min={0}
            placeholder="no limit"
            value={policy.max_errors_total ?? ''}
            disabled={disabled}
            onChange={(e) => set({ max_errors_total: numOrNull(e.target.value) })}
            style={{ width: 90 }}
          />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor={id('on-worker')}>
            When a worker process dies
          </label>
          <select
            id={id('on-worker')}
            value={policy.on_worker_failure}
            disabled={disabled}
            onChange={(e) => set({ on_worker_failure: e.target.value as TrainingErrorPolicy['on_worker_failure'] })}
          >
            <option value="retry">Retry its runs</option>
            <option value="pause">Pause the Training</option>
          </select>
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor={id('max-retries')}>
            Retries per run
          </label>
          <input
            id={id('max-retries')}
            type="number"
            min={0}
            value={policy.max_retries}
            disabled={disabled || policy.on_worker_failure !== 'retry'}
            onChange={(e) => set({ max_retries: numOrNull(e.target.value) ?? 0 })}
            style={{ width: 70 }}
          />
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor={id('on-config')}>
            When the engine configuration changes
          </label>
          <select
            id={id('on-config')}
            value={policy.on_config_change}
            disabled={disabled}
            onChange={(e) => set({ on_config_change: e.target.value as TrainingErrorPolicy['on_config_change'] })}
          >
            <option value="pause">Pause</option>
            <option value="adopt">Continue under the new configuration</option>
          </select>
        </div>
      </div>
    </div>
  );
}
