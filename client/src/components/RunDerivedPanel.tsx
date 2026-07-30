// ---------------------------------------------------------------------------
// RunDerivedPanel — what this Run turned out to be
// ---------------------------------------------------------------------------
//
// The other half of `GET /api/runs/{id}/parameters`, and deliberately a separate
// panel from the settable one. Fixed parameters are inputs, chosen before the first
// codelet; these are outputs — which numeric backend was actually selected, how many
// shards sharding settled on, the config and memory hashes, the Training Session,
// and the free-running telemetry when there is any. Presenting them as though they
// could be set would be a lie about how the engine works, so the panel says
// read-only in its header and renders nothing you can type into.
//
// It also reads back the *fixed* half, but only as a list of which parameters
// differed from the default. That is the answer to "did my override actually reach
// the engine?", which is not a question the form can answer — the form knows what it
// sent, and the engine knows what it ran.
//
// Refetched when the run changes and when its status does, rather than on every
// codelet: the interesting values here either never change for a run or appear
// exactly once, when it finishes.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import { getRunParameters } from '@/api/client';
import type { FreeRunTelemetry, RunParametersView } from '@/types';

export function RunDerivedPanel() {
  const runId = useRunStore((s) => s.runId);
  const status = useRunStore((s) => s.status);
  const epoch = useRunStore((s) => s.epoch);

  const [view, setView] = useState<RunParametersView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(() => {
    if (runId === null) {
      setView(null);
      return;
    }
    getRunParameters(runId)
      .then((v) => {
        setView(v);
        setError(null);
      })
      .catch((e: unknown) => {
        setView(null);
        setError(e instanceof Error ? e.message : 'Could not read this run');
      });
  }, [runId]);

  useEffect(() => {
    refresh();
  }, [refresh, status, epoch]);

  if (runId === null) return null;

  const derived = view?.derived;
  const telemetry = derived?.free_running;

  return (
    <div style={groupStyle}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={headerButtonStyle}
      >
        <span style={groupLabelStyle}>What this run is — read-only</span>
        <span style={{ flex: 1 }} />
        {telemetry !== undefined && (
          <span
            className="mono"
            title="This run executed free-running, across more than one worker."
            style={{
              fontSize: 9,
              fontWeight: 700,
              color: 'var(--text-accent)',
              border: '1px solid var(--text-accent)',
              borderRadius: 3,
              padding: '0 4px',
            }}
          >
            free-running
          </span>
        )}
        <span className="text-muted" style={{ fontSize: 11 }}>
          {open ? '▾' : '▸'}
        </span>
      </button>

      {!open && (
        <div className="text-xs text-muted" style={{ marginTop: 4 }}>
          Derived from the run rather than set on it: backend, sharding, hashes,
          session, and free-running telemetry.
        </div>
      )}

      {open && (
        <div style={{ marginTop: 6 }}>
          {error !== null && (
            <div className="text-xs" style={{ color: 'var(--warning)' }}>
              {error}
            </div>
          )}

          {derived !== undefined && (
            <>
              <Section title="Execution">
                <Row label="Persistence mode" value={derived.mode} />
                <Row
                  label="Workers"
                  value={derived.workers}
                  hint={
                    (derived.workers ?? 1) > 1
                      ? 'Free-running: codelets across CPU cores with no global barrier. A seed no longer reproduces this run.'
                      : 'Serial — the reference mode. Seed and problem reproduce the run exactly.'
                  }
                />
                <Row label="Status" value={derived.status} />
                <Row label="Codelets executed" value={derived.codelet_count} />
                <Row label="Temperature" value={derived.temperature} />
                <Row
                  label="Justify mode"
                  value={derived.justify_mode === undefined ? undefined : String(derived.justify_mode)}
                  hint="The answer was given for the engine to justify rather than discovered by it."
                />
              </Section>

              <Section title="Substrate">
                <Row
                  label="Numeric backend"
                  value={derived.numeric_backend ?? 'engine loops'}
                  hint="Which implementation of the engine's array arithmetic actually ran. Selected by the substrate at this Slipnet size, not chosen per run."
                />
                <Row label="Numeric device" value={derived.numeric_device} />
                <Row label="Slipnet nodes" value={derived.slipnet_nodes} />
                <Row
                  label="Coderack shards"
                  value={derived.coderack_shards}
                  hint="How many racks the coderack divided itself into. 1 is the unsharded serial rack; free-running settles on more."
                />
                <Row
                  label="Capacity per shard"
                  value={derived.coderack_capacity_per_shard}
                  hint="Sharding divides the rack's capacity rather than replicating it, and a shard below 25 is too small for the jootsing sequence to complete."
                />
                <Row
                  label="Staleness delay"
                  value={derived.staleness_delay}
                  hint="How many codelets old the values a codelet reads may be."
                />
              </Section>

              <Section title="Identity">
                <Row label="Seed" value={derived.seed} />
                <Row
                  label="Recorded"
                  value={derived.recorded === undefined ? undefined : String(derived.recorded)}
                  hint="False for a Fast Run: there is no database row, which is the mode keeping its promise."
                />
                <Row label="Config hash" value={shorten(derived.config_hash)} title={derived.config_hash ?? undefined} />
                <Row label="Memory hash" value={shorten(derived.memory_hash)} title={derived.memory_hash ?? undefined} />
                <Row label="Training Session" value={derived.session_id} />
              </Section>

              {telemetry !== undefined && <Telemetry telemetry={telemetry} />}

              {view !== null && (
                <Section title="Fixed parameters, as the engine read them">
                  {view.overridden.length === 0 ? (
                    <div className="text-xs text-muted">
                      All {Object.keys(view.fixed).length} at their defaults.
                    </div>
                  ) : (
                    <div className="text-xs" style={{ lineHeight: 1.6 }}>
                      {view.overridden.map((name) => (
                        <div key={name} className="mono" style={{ fontSize: 10 }}>
                          <span style={{ color: 'var(--warning)' }}>{name}</span>{' '}
                          <span style={{ color: 'var(--text-primary)' }}>
                            {format(view.fixed[name])}
                          </span>{' '}
                          <span className="text-muted">
                            (default {format(view.defaults[name])})
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </Section>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * How the run actually divided, which cannot be reconstructed afterwards.
 *
 * A free-running run is one draw: the conflict rate and the per-worker split are the
 * only account of how it was taken, and nothing in the run's record implies them.
 */
function Telemetry({ telemetry }: { telemetry: FreeRunTelemetry }) {
  const total = telemetry.per_worker.reduce((a, b) => a + b, 0) || 1;
  return (
    <Section title="Free-running telemetry">
      <Row label="Workers" value={telemetry.workers} />
      <Row label="Codelets" value={telemetry.codelets} />
      <Row label="Wall time" value={`${telemetry.seconds}s`} />
      <Row label="Codelets/second" value={telemetry.codelets_per_second} />
      <Row
        label="Conflicts"
        value={`${telemetry.conflicts} (${(telemetry.conflict_rate * 100).toFixed(1)}%)`}
        hint="Codelets whose read-set had moved by the time they committed. A lost race is folded into the architecture's own fizzle outcome, so a conflict is not an error."
      />
      <Row label="Update cycles" value={telemetry.update_cycles} />

      <div className="text-xs text-muted" style={{ marginTop: 4 }}>
        Codelets per worker
      </div>
      {telemetry.per_worker.map((count, i) => (
        <div
          key={i}
          style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 1 }}
        >
          <span className="mono text-muted" style={{ fontSize: 9, width: 22 }}>
            w{i}
          </span>
          <div
            style={{
              flex: 1,
              height: 6,
              background: 'var(--bg-primary)',
              borderRadius: 3,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${(count / total) * 100}%`,
                height: '100%',
                background: 'var(--text-accent)',
              }}
            />
          </div>
          <span className="mono text-muted" style={{ fontSize: 9, width: 40, textAlign: 'right' }}>
            {count}
          </span>
        </div>
      ))}
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <div
        className="text-xs"
        style={{
          fontSize: 9,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: 0.4,
          color: 'var(--text-secondary)',
          borderBottom: '1px solid var(--border)',
          marginBottom: 2,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  hint,
  title,
}: {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
  title?: string;
}) {
  if (value === undefined || value === null) return null;
  return (
    <div
      style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 10 }}
      title={hint ?? title}
    >
      <span className="text-muted">{label}</span>
      <span className="mono" style={{ color: 'var(--text-primary)' }} title={title}>
        {value}
      </span>
    </div>
  );
}

function shorten(hash: string | null | undefined): string | undefined {
  if (hash === null || hash === undefined) return undefined;
  return hash.slice(0, 12);
}

function format(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} nodes`;
  if (value !== null && typeof value === 'object') {
    return `${Object.keys(value).length} entries`;
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const groupStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px dashed var(--border)',
  borderRadius: 4,
  padding: 10,
};

const groupLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: 'var(--text-secondary)',
};

const headerButtonStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  width: '100%',
  background: 'transparent',
  border: 'none',
  padding: 0,
  cursor: 'pointer',
  textAlign: 'left',
  color: 'var(--text-secondary)',
};
