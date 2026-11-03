// ---------------------------------------------------------------------------
// Petacat -- Training Mode Session: the new-Training Mode Session form
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import { addSessionProblems, createSession, describeApiError, getSwarmStatus } from '@/api/client';
import type {
  SessionErrorPolicy,
  SessionLimits,
  SessionSettings,
  SessionSummary,
} from '@/types';
import { chunk, parseProblemText } from './problemText';
import { FALLBACK_POLICY, PolicyFields } from './PolicyFields';
import { ProblemPreview, ProblemTextInput } from './ProblemTextInput';
import {
  cardStyle,
  ControlHelp,
  errorStyle,
  fieldGroupStyle,
  labelStyle,
  sectionLabelStyle,
} from './shared';

const DEFAULT_SEEDS = 100;
const DEFAULT_MAX_CODELETS = 20_000;
const FALLBACK_REQUEST_SIZE = 500;

/** The configuration a new session starts from, when the manager chose one (not the default). */
export interface ConfigurationBase {
  /** `settings.configuration_base`: `'global'`, `'standard'` or `{ session_id }`. */
  value: 'global' | 'standard' | { session_id: number };
  /** For the person reading the form. */
  label: string;
}

interface Props {
  /** Set by the Admin view's "New session from this configuration". */
  configurationBase?: ConfigurationBase | null;
  limits: SessionLimits | null;
  /** The server's defaults for the settings and the policy, when it has said. */
  defaults: { settings: SessionSettings; policy: SessionErrorPolicy } | null;
  /** The Training Mode Session was created; `warning` is set when only some problems were added. */
  onCreated: (session: SessionSummary, warning: string | null) => void;
  onCancel: () => void;
}

export function NewSessionForm({ configurationBase = null, limits, defaults, onCreated, onCancel }: Props) {
  const overrides = useRunStore((s) => s.parameterOverrides);
  const overrideCount = Object.keys(overrides).length;

  const [name, setName] = useState('');
  const [seeds, setSeeds] = useState(String(defaults?.settings.seeds_per_problem ?? DEFAULT_SEEDS));
  const [seedStart, setSeedStart] = useState(String(defaults?.settings.seed_start ?? 1));
  const [maxCodelets, setMaxCodelets] = useState(
    String(defaults?.settings.max_codelets ?? DEFAULT_MAX_CODELETS),
  );
  const [useOverrides, setUseOverrides] = useState(false);
  const [backend, setBackend] = useState('');
  const [backends, setBackends] = useState<string[]>([]);
  const [policy, setPolicy] = useState<SessionErrorPolicy>(defaults?.policy ?? FALLBACK_POLICY);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The defaults can arrive after the form opens; take them unless the researcher has typed.
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!defaults || touched) return;
    setSeeds(String(defaults.settings.seeds_per_problem));
    setSeedStart(String(defaults.settings.seed_start));
    setMaxCodelets(String(defaults.settings.max_codelets));
    setPolicy(defaults.policy);
  }, [defaults, touched]);

  useEffect(() => {
    let cancelled = false;
    getSwarmStatus()
      .then((s) => {
        if (!cancelled) setBackends(s.backends ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const parsed = useMemo(() => parseProblemText(text), [text]);

  const maxSeeds = limits?.max_seeds_per_problem ?? Number.MAX_SAFE_INTEGER;
  const maxCodeletsLimit = limits?.max_codelets ?? Number.MAX_SAFE_INTEGER;
  const seedsN = Number(seeds);
  const startN = Number(seedStart);
  const codeletsN = Number(maxCodelets);
  const nameOk = name.trim() !== '';
  const seedsOk = Number.isInteger(seedsN) && seedsN >= 1 && seedsN <= maxSeeds;
  const startOk = Number.isInteger(startN) && seedStart.trim() !== '';
  const codeletsOk = Number.isInteger(codeletsN) && codeletsN >= 1 && codeletsN <= maxCodeletsLimit;

  const problem = !nameOk
    ? 'Give the Training Mode Session a name.'
    : !seedsOk
      ? `Seeds per problem must be a whole number from 1${limits ? ` to ${maxSeeds.toLocaleString()}` : ''}.`
      : !startOk
        ? 'First seed must be a whole number.'
        : !codeletsOk
          ? `Max codelets must be a whole number from 1${limits ? ` to ${maxCodeletsLimit.toLocaleString()}` : ''}.`
          : null;

  const touch = <T,>(set: (v: T) => void) => (v: T) => {
    setTouched(true);
    set(v);
  };

  const handleCreate = async () => {
    setBusy(true);
    setError(null);
    const parts = chunk(parsed.problems, limits?.max_problems_per_request ?? FALLBACK_REQUEST_SIZE);
    let created: SessionSummary | null = null;
    let added = 0;
    try {
      const first = await createSession({
        name: name.trim(),
        settings: {
          seeds_per_problem: seedsN,
          seed_start: startN,
          max_codelets: codeletsN,
          ...(useOverrides && overrideCount > 0 ? { parameters: overrides } : {}),
          ...(backend !== '' ? { backend } : {}),
          ...(configurationBase ? { configuration_base: configurationBase.value } : {}),
        } as Partial<SessionSettings>,
        policy,
        problems: parts[0],
      });
      created = first.session;
      added = first.added;
      for (const part of parts.slice(1)) {
        const more = await addSessionProblems(created.id, part);
        created = more.session;
        added += more.added;
      }
      onCreated(created, null);
    } catch (err) {
      if (created) {
        // The Training Mode Session exists: take the researcher to it rather than leave it orphaned.
        onCreated(
          created,
          `${describeApiError(err, 'add the remaining problems')} ${added.toLocaleString()} of ` +
            `${parsed.problems.length.toLocaleString()} problems were added; add the rest with Add problems.`,
        );
      } else {
        setError(describeApiError(err, 'create the Training Mode Session'));
        setBusy(false);
      }
    }
  };

  return (
    <div style={cardStyle} data-testid="new-session-form">
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={sectionLabelStyle}>New session</div>
        <ControlHelp topic="session_new" label="New session" />
      </div>
      <div className="text-xs text-muted" style={{ marginTop: 4 }}>
        A Training Mode Session is a named episode: many problems, each over many seeds. The settings below are fixed once it
        is created. {configurationBase ? 'It never changes Metacat Mode.' : 'It copies the global configuration that Metacat Mode uses and never changes it.'}
        <ControlHelp topic="starting_conceptual_state" label="the Starting Conceptual State" />
      </div>

      {configurationBase && (
        <div className="text-xs" role="note" data-testid="configuration-base-line" style={{ marginTop: 6 }}>
          Its Starting Conceptual State is a copy of {configurationBase.label}.
        </div>
      )}

      <div style={{ ...fieldGroupStyle, marginTop: 8 }}>
        <label style={labelStyle} htmlFor="session-name">
          Name (required)
        </label>
        <input
          id="session-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={busy}
          maxLength={200}
          style={{ maxWidth: 320 }}
        />
      </div>

      <div style={fieldGroupStyle}>
        <span style={{ display: 'flex', alignItems: 'center' }}>
          <span style={labelStyle}>Episodic Memory</span>
          <ControlHelp topic="training_mode_session_memory" label="Episodic Memory" />
        </span>
        <div className="text-xs text-muted" data-testid="memory-help-line">
          Every Training Mode Session has its own Episodic Memory, never cleared and never shared with Metacat Mode. Each run copies it when it starts and holds it static; what a run adds
          reaches only the runs that start after it finishes. A new Training Mode Session is stopped: press Start to run it.
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <div style={fieldGroupStyle}>
          <span style={{ display: 'flex', alignItems: 'center' }}>
            <label style={labelStyle} htmlFor="session-seeds">
              Seeds per problem
            </label>
            <ControlHelp topic="session_seeds" label="Seeds per problem" />
          </span>
          <input
            id="session-seeds"
            type="number"
            min={1}
            value={seeds}
            onChange={(e) => touch(setSeeds)(e.target.value)}
            disabled={busy}
            style={{ width: 90 }}
          />
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="session-seed-start">
            First seed
          </label>
          <input
            id="session-seed-start"
            type="number"
            value={seedStart}
            onChange={(e) => touch(setSeedStart)(e.target.value)}
            disabled={busy}
            style={{ width: 80 }}
          />
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="session-max-codelets" title="A run that reaches it gives up">
            Max codelets per run
          </label>
          <input
            id="session-max-codelets"
            type="number"
            min={1}
            value={maxCodelets}
            onChange={(e) => touch(setMaxCodelets)(e.target.value)}
            disabled={busy}
            style={{ width: 100 }}
          />
          <div className="text-xs text-muted">A run that reaches it gives up.</div>
        </div>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="session-backend">
            Backend (advanced)
          </label>
          <select
            id="session-backend"
            value={backend}
            disabled={busy}
            onChange={(e) => setBackend(e.target.value)}
          >
            <option value="">Default</option>
            {backends.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </div>
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 8 }}>
        <input
          type="checkbox"
          checked={useOverrides}
          onChange={(e) => setUseOverrides(e.target.checked)}
          disabled={busy}
        />
        Use the dashboard's parameter overrides
        <span className="text-xs text-muted">
          ({overrideCount === 0 ? 'none set' : `${overrideCount} set`})
        </span>
      </label>

      <details style={{ marginBottom: 10 }} data-testid="policy-section">
        <summary style={{ cursor: 'pointer', fontSize: 12 }}>When things go wrong</summary>
        <div style={{ marginTop: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center' }} className="text-xs text-muted">
            The error policy; it can be changed later.
            <ControlHelp topic="session_error_policy" label="the error policy" />
          </div>
          <PolicyFields
            idPrefix="new-policy"
            policy={policy}
            onChange={touch(setPolicy)}
            disabled={busy}
          />
        </div>
      </details>

      <ProblemTextInput id="session-problems" value={text} onChange={setText} disabled={busy} demos />
      <ProblemPreview parsed={parsed} seedsPerProblem={seedsOk ? seedsN : DEFAULT_SEEDS} />

      {problem && (
        <div className="text-xs text-muted" style={{ marginTop: 6 }}>
          {problem}
        </div>
      )}
      {error && (
        <div role="alert" style={{ ...errorStyle, marginTop: 6 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
        <button onClick={() => void handleCreate()} disabled={busy || problem !== null}>
          {busy ? 'Creating…' : 'Create session'}
        </button>
        <button onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}
