// ---------------------------------------------------------------------------
// RunParametersPanel — the twenty-five parameters a Run is fixed with
// ---------------------------------------------------------------------------
//
// These are inputs, not settings: the engine reads every one of them before or
// during the first codelet and none of them changes again for the life of the Run.
// That is why the panel lives in the run-creation area next to Recording — the two
// behave identically, in that changing either means the next press of Run starts a
// new run rather than continuing this one — and why nothing here is pushed to the
// server on change. There is no endpoint to push it to, and there should not be.
//
// Twenty-five controls would swamp a panel that is otherwise four buttons and three
// sliders, so:
//
//   * the whole section is collapsed until asked for, and its header carries the
//     one number that matters when it is closed — how many are off their defaults;
//   * inside, each group is collapsed too, except a group holding an override,
//     which opens itself, because a changed value that is two clicks from view is
//     a changed value nobody will find again;
//   * an empty field means "the default", so the common path is to touch none of
//     them and the panel stays visibly empty of decisions.
//
// The catalogue — kinds, bounds, defaults, prose — is fetched from the server. The
// bounds enforced below are the same ones the API validates against; duplicating
// them here would give a control that offers values the server rejects.
//
// `node_list` and `node_map` are shown but not editable. Two of the twenty-five are
// lists of Slipnet node names and one is a map from link labels to lengths, and an
// editor for those is a different piece of work from a number field: it needs the
// node vocabulary to validate against, and a wrong name is not a typo the run
// recovers from. They are displayed in full, with their values, and the panel says
// where they *can* be changed — globally, in Configuration → Engine Params. Showing
// the value and saying plainly that it is read-only here is better than a control
// that half works.
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import {
  parameterErrors,
  useParameterCatalogue,
} from '@/hooks/useParameterCatalogue';
import type { RunParameterSpec, RunParameterValue } from '@/types';

/** Are these the same value, for the purpose of "has it been changed?" */
function sameValue(a: RunParameterValue | undefined, b: RunParameterValue): boolean {
  if (a === undefined) return true;
  if (Array.isArray(a) || Array.isArray(b) || typeof a === 'object' || typeof b === 'object') {
    return JSON.stringify(a) === JSON.stringify(b);
  }
  return a === b;
}

function isEditable(spec: RunParameterSpec): boolean {
  return spec.kind === 'int' || spec.kind === 'float' || spec.kind === 'bool';
}

export function RunParametersPanel() {
  const { specs, isLoading, error, load } = useParameterCatalogue();
  const overrides = useRunStore((s) => s.parameterOverrides);
  const setOverride = useRunStore((s) => s.setParameterOverride);
  const clearOverride = useRunStore((s) => s.clearParameterOverride);
  const clearAll = useRunStore((s) => s.clearAllParameterOverrides);
  const isRunning = useRunStore((s) => s.status === 'running');

  const [open, setOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    load();
  }, [load]);

  const errors = useMemo(() => parameterErrors(specs, overrides), [specs, overrides]);

  const changed = useMemo(
    () =>
      specs.filter((s) => !sameValue(overrides[s.name], s.default)).map((s) => s.name),
    [specs, overrides],
  );

  const groups = useMemo(() => {
    const byGroup = new Map<string, RunParameterSpec[]>();
    for (const spec of specs) {
      const list = byGroup.get(spec.group);
      if (list) list.push(spec);
      else byGroup.set(spec.group, [spec]);
    }
    return [...byGroup.entries()];
  }, [specs]);

  /**
   * A group opens on demand, and also whenever it holds a changed value — otherwise
   * the panel could report "3 changed" with every group shut and no indication of
   * which three.
   */
  const groupIsOpen = (group: string, members: RunParameterSpec[]): boolean =>
    openGroups[group] ?? members.some((m) => changed.includes(m.name));

  const setNumber = (spec: RunParameterSpec, raw: string) => {
    if (raw.trim() === '') {
      clearOverride(spec.name);
      return;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) return;
    // Typing the default back in removes the override rather than pinning the
    // parameter to today's value of it. The two are indistinguishable until somebody
    // edits the default in the Admin panel, at which point a pinned value is an
    // override nobody chose.
    if (value === spec.default) clearOverride(spec.name);
    else setOverride(spec.name, value);
  };

  const setBool = (spec: RunParameterSpec, value: boolean) => {
    if (value === spec.default) clearOverride(spec.name);
    else setOverride(spec.name, value);
  };

  return (
    <div style={groupStyle}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={headerButtonStyle}
      >
        <span style={groupLabelStyle}>Engine parameters</span>
        <span style={{ flex: 1 }} />
        {changed.length > 0 && (
          <span
            className="mono"
            title={`Changed from the default: ${changed.join(', ')}`}
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: 'var(--warning)',
              border: '1px solid var(--warning)',
              borderRadius: 3,
              padding: '0 4px',
            }}
          >
            {changed.length} changed
          </span>
        )}
        <span className="text-muted" style={{ fontSize: 11 }}>
          {open ? '▾' : '▸'}
        </span>
      </button>

      {!open && (
        <div className="text-xs text-muted" style={{ marginTop: 4 }}>
          {changed.length === 0
            ? 'Every parameter at its default. Press Run and none of this matters.'
            : 'Fixed at creation, so a change here starts a new run.'}
        </div>
      )}

      {open && (
        <div style={{ marginTop: 6 }}>
          {isLoading && <div className="text-xs text-muted">Loading parameters…</div>}
          {error !== null && (
            <div className="text-xs" style={{ color: 'var(--error)' }}>
              {error} — the run will use the server's defaults.
            </div>
          )}

          <div className="text-xs text-muted" style={{ marginBottom: 6 }}>
            Read by the engine before the first codelet and constant for the whole run,
            so changing one starts a new run. An empty field means the default.
          </div>

          {changed.length > 0 && (
            <button
              onClick={clearAll}
              disabled={isRunning}
              title="Put every parameter back to its default."
              style={{ fontSize: 10, marginBottom: 6 }}
            >
              Reset all {changed.length} to defaults
            </button>
          )}

          {groups.map(([group, members]) => {
            const expanded = groupIsOpen(group, members);
            const groupChanged = members.filter((m) => changed.includes(m.name)).length;
            return (
              <div key={group} style={{ marginBottom: 4 }}>
                <button
                  onClick={() =>
                    setOpenGroups((g) => ({ ...g, [group]: !expanded }))
                  }
                  aria-expanded={expanded}
                  style={{
                    ...headerButtonStyle,
                    padding: '2px 0',
                    fontSize: 11,
                    color: 'var(--text-primary)',
                  }}
                >
                  <span>{expanded ? '▾' : '▸'} {group}</span>
                  <span style={{ flex: 1 }} />
                  {groupChanged > 0 && (
                    <span className="mono" style={{ fontSize: 9, color: 'var(--warning)' }}>
                      {groupChanged}
                    </span>
                  )}
                  <span className="text-muted" style={{ fontSize: 9 }}>
                    {members.length}
                  </span>
                </button>

                {expanded && (
                  <div
                    style={{
                      borderLeft: '1px solid var(--border)',
                      paddingLeft: 6,
                      marginLeft: 3,
                    }}
                  >
                    {members.map((spec) => (
                      <ParameterControl
                        key={spec.name}
                        spec={spec}
                        value={overrides[spec.name]}
                        error={errors[spec.name]}
                        changed={changed.includes(spec.name)}
                        disabled={isRunning}
                        onNumber={(raw) => setNumber(spec, raw)}
                        onBool={(v) => setBool(spec, v)}
                        onReset={() => clearOverride(spec.name)}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// One parameter
// ---------------------------------------------------------------------------

interface ControlProps {
  spec: RunParameterSpec;
  value: RunParameterValue | undefined;
  error: string | undefined;
  changed: boolean;
  disabled: boolean;
  onNumber: (raw: string) => void;
  onBool: (value: boolean) => void;
  onReset: () => void;
}

function ParameterControl({
  spec,
  value,
  error,
  changed,
  disabled,
  onNumber,
  onBool,
  onReset,
}: ControlProps) {
  const [showDescription, setShowDescription] = useState(false);
  const editable = isEditable(spec);

  return (
    <div
      style={{
        padding: '4px 0',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <label
          htmlFor={`param-${spec.name}`}
          style={{
            fontSize: 11,
            flex: 1,
            color: changed ? 'var(--warning)' : 'var(--text-secondary)',
          }}
        >
          {spec.label}
          {changed && (
            <span title="Changed from the default" style={{ marginLeft: 3 }}>
              *
            </span>
          )}
        </label>

        {/* The catalogue's own prose, not a paraphrase of it: it is written for
            somebody deciding whether to change the value, which is exactly who is
            looking at this control. Behind a toggle because twenty-five paragraphs
            at once is not a form. */}
        <button
          onClick={() => setShowDescription((s) => !s)}
          aria-label={`What ${spec.label} does`}
          aria-expanded={showDescription}
          title={spec.description}
          style={{
            background: 'none',
            border: '1px solid var(--border)',
            borderRadius: 3,
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            fontSize: 9,
            lineHeight: 1,
            padding: '1px 4px',
          }}
        >
          ?
        </button>

        {editable ? (
          spec.kind === 'bool' ? (
            <input
              id={`param-${spec.name}`}
              type="checkbox"
              checked={typeof value === 'boolean' ? value : spec.default === true}
              onChange={(e) => onBool(e.target.checked)}
              disabled={disabled}
            />
          ) : (
            <input
              id={`param-${spec.name}`}
              type="number"
              value={typeof value === 'number' ? String(value) : ''}
              placeholder={String(spec.default)}
              min={spec.minimum ?? undefined}
              max={spec.maximum ?? undefined}
              step={spec.kind === 'float' ? 0.01 : 1}
              onChange={(e) => onNumber(e.target.value)}
              disabled={disabled}
              style={{
                width: 78,
                fontSize: 11,
                borderColor: error ? 'var(--error)' : undefined,
              }}
            />
          )
        ) : (
          <span
            className="mono text-muted"
            style={{ fontSize: 9 }}
            title="Set globally, in Configuration → Engine Params"
          >
            read-only
          </span>
        )}

        <button
          onClick={onReset}
          disabled={disabled || !changed}
          aria-label={`Reset ${spec.label} to its default`}
          title={`Reset to the default, ${formatValue(spec.default)}`}
          style={{
            background: 'none',
            border: 'none',
            color: changed ? 'var(--text-accent)' : 'var(--border)',
            cursor: changed ? 'pointer' : 'default',
            fontSize: 11,
            padding: '0 2px',
          }}
        >
          ↺
        </button>
      </div>

      <div className="text-xs text-muted" style={{ fontSize: 9, marginTop: 1 }}>
        <span className="mono">{spec.name}</span>
        {' · default '}
        <span className="mono">{formatValue(spec.default)}</span>
        {editable && spec.minimum !== null && spec.maximum !== null && (
          <>
            {' · '}
            {spec.minimum}–{spec.maximum}
          </>
        )}
      </div>

      {!editable && <ReadOnlyValue spec={spec} />}

      {error !== undefined && (
        <div className="text-xs" style={{ color: 'var(--error)', fontSize: 10 }}>
          {error}
        </div>
      )}

      {showDescription && (
        <div
          className="text-xs text-muted"
          style={{ marginTop: 3, lineHeight: 1.5 }}
        >
          {spec.description}
        </div>
      )}
    </div>
  );
}

/**
 * The value of a parameter there is no control for, shown in full.
 *
 * Shown rather than hidden: a reader looking at "what is this run fixed with?" needs
 * to know which concepts are clamped at the start whether or not this form can change
 * them, and the alternative — omitting three of the twenty-five — would make the panel
 * quietly incomplete.
 */
function ReadOnlyValue({ spec }: { spec: RunParameterSpec }) {
  const entries: [string, string][] = Array.isArray(spec.default)
    ? spec.default.map((name) => [String(name), ''])
    : Object.entries(spec.default as Record<string, number>).map(([k, v]) => [
        k,
        String(v),
      ]);

  return (
    <div style={{ marginTop: 2 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
        {entries.map(([name, extra]) => (
          <span
            key={name}
            className="mono"
            style={{
              fontSize: 9,
              padding: '0 3px',
              borderRadius: 2,
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
            }}
          >
            {name}
            {extra !== '' && `:${extra}`}
          </span>
        ))}
      </div>
      <div className="text-xs text-muted" style={{ fontSize: 9, marginTop: 2 }}>
        Not editable per run — a wrong Slipnet node name is not a typo the run recovers
        from, and validating one needs the node vocabulary this form does not have.
        Change it globally in Configuration → Engine Params.
      </div>
    </div>
  );
}

function formatValue(value: RunParameterValue): string {
  if (Array.isArray(value)) return `${value.length} nodes`;
  if (typeof value === 'object') return `${Object.keys(value).length} entries`;
  return String(value);
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const groupStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
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
