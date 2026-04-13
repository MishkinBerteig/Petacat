// ---------------------------------------------------------------------------
// AdminPanel — Destructive/utility operations with SSOT help text
// ---------------------------------------------------------------------------
//
// Every section in this panel is backed by a help topic in the help text SSOT
// (seed_data/help_topics.en.json). On mount we fetch the three `admin_*`
// topics via GET /api/docs/components/{key} and render their structured
// metadata.user_description / metadata.technical_description bullet lists.
//
// To add, remove, or reword any admin action description: edit the JSON,
// click "Regenerate Help Documentation" (or restart the backend), and the
// panel will pick up the new content on the next page load. No TypeScript
// edits required for description changes.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useState } from 'react';
import { useRunStore } from '@/store/runStore';
import {
  getComponentHelp,
  regenerateHelpDocs,
  type RegenerateHelpResult,
} from '@/api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Metadata shape for an `admin_*` topic. */
interface AdminActionMetadata {
  kind?: 'admin_action';
  button_variant?: 'warning' | 'danger' | 'utility';
  user_description?: string[];
  technical_description?: string[];
}

interface AdminActionTopic {
  title: string;
  short_desc: string;
  metadata: AdminActionMetadata;
}

type TopicLoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; topic: AdminActionTopic };

const ACTION_KEYS = [
  'admin_regenerate_help',
  'admin_clear_memory',
  'admin_full_reset',
] as const;

type ActionKey = (typeof ACTION_KEYS)[number];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AdminPanel() {
  const store = useRunStore();

  // Help-topic content for each action section (fetched from the API)
  const [topicState, setTopicState] = useState<Record<ActionKey, TopicLoadState>>(
    () => ({
      admin_regenerate_help: { kind: 'loading' },
      admin_clear_memory: { kind: 'loading' },
      admin_full_reset: { kind: 'loading' },
    }),
  );

  const loadTopics = useCallback(async () => {
    await Promise.all(
      ACTION_KEYS.map(async (key) => {
        try {
          const data = await getComponentHelp(key);
          setTopicState((prev) => ({
            ...prev,
            [key]: {
              kind: 'ready',
              topic: {
                title: data.name,
                short_desc: data.short_desc,
                metadata: (data.metadata ?? {}) as AdminActionMetadata,
              },
            },
          }));
        } catch (err) {
          setTopicState((prev) => ({
            ...prev,
            [key]: {
              kind: 'error',
              message: err instanceof Error ? err.message : 'Failed to load',
            },
          }));
        }
      }),
    );
  }, []);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  // --- Regenerate help documentation ---
  const [regenStatus, setRegenStatus] = useState<
    | { kind: 'idle' }
    | { kind: 'loading' }
    | { kind: 'success'; result: RegenerateHelpResult }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  const handleRegenerateHelp = useCallback(async () => {
    setRegenStatus({ kind: 'loading' });
    try {
      const result = await regenerateHelpDocs();
      setRegenStatus({ kind: 'success', result });
      // Reload help topics so the panel reflects any JSON edits immediately
      await loadTopics();
    } catch (err) {
      setRegenStatus({
        kind: 'error',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  }, [loadTopics]);

  // --- Clear episodic memory ---
  const handleClearMemory = useCallback(async () => {
    if (
      window.confirm(
        'Clear episodic memory?\n\n'
          + 'This removes all stored answer and snag descriptions from past runs. '
          + 'It does NOT reset the current run or delete run history.\n\n'
          + 'This cannot be undone.'
      )
    ) {
      try {
        await fetch('/api/memory', { method: 'DELETE' });
        await store.refreshMemory();
        useRunStore.setState({ epoch: useRunStore.getState().epoch + 1 });
      } catch {
        // ignore
      }
    }
  }, [store]);

  // --- Full reset ---
  const handleFullReset = useCallback(async () => {
    if (
      window.confirm(
        'Full reset?\n\n'
          + 'This will:\n'
          + '  - Stop any running run\n'
          + '  - Delete ALL runs and their history\n'
          + '  - Clear all episodic memory\n'
          + '  - Reset the UI to its initial state\n\n'
          + 'This cannot be undone.'
      )
    ) {
      await store.fullReset();
    }
  }, [store]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 24,
        padding: 20,
        height: '100%',
        boxSizing: 'border-box',
        overflowY: 'auto',
      }}
    >
      {/* ---- Row 1: Regenerate Help Documentation (utility, non-destructive) ---- */}
      <ActionSection
        state={topicState.admin_regenerate_help}
        action={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button
              onClick={handleRegenerateHelp}
              disabled={regenStatus.kind === 'loading'}
              style={utilityButtonStyle}
            >
              {regenStatus.kind === 'loading'
                ? 'Regenerating...'
                : 'Regenerate Help Documentation'}
            </button>

            {regenStatus.kind === 'success' && (
              <span style={{ fontSize: 11, color: 'var(--success)' }}>
                OK — {regenStatus.result.topics_loaded} topics (
                {regenStatus.result.components} components,{' '}
                {regenStatus.result.glossary} glossary). HELP.md:{' '}
                {regenStatus.result.help_md_changed ? 'updated' : 'unchanged'}
                {', '}
                helpTopics.ts:{' '}
                {regenStatus.result.ts_constants_changed ? 'updated' : 'unchanged'}.
              </span>
            )}

            {regenStatus.kind === 'error' && (
              <span style={{ fontSize: 11, color: 'var(--error)' }}>
                Failed: {regenStatus.message}
              </span>
            )}
          </div>
        }
      />

      {/* ---- Row 2: destructive operations (side by side) ---- */}
      <div style={{ display: 'flex', gap: 24, flex: 1, minHeight: 0 }}>
        <div style={columnStyle}>
          <ActionSection
            state={topicState.admin_clear_memory}
            action={
              <button onClick={handleClearMemory} style={warningButtonStyle}>
                Clear Episodic Memory
              </button>
            }
          />
        </div>

        <div style={columnStyle}>
          <ActionSection
            state={topicState.admin_full_reset}
            action={
              <button onClick={handleFullReset} style={dangerButtonStyle}>
                Full Reset (delete everything)
              </button>
            }
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActionSection — renders one admin topic's title + user/technical bullets + action button
// ---------------------------------------------------------------------------

function ActionSection({
  state,
  action,
}: {
  state: TopicLoadState;
  action: React.ReactNode;
}) {
  if (state.kind === 'loading') {
    return (
      <div style={docBlockStyle}>
        <span className="text-muted text-sm">Loading help content...</span>
      </div>
    );
  }

  if (state.kind === 'error') {
    return (
      <div style={docBlockStyle}>
        <span style={{ color: 'var(--error)', fontSize: 12 }}>
          Failed to load help: {state.message}
        </span>
      </div>
    );
  }

  const { topic } = state;
  const userBullets = topic.metadata.user_description ?? [];
  const techBullets = topic.metadata.technical_description ?? [];

  return (
    <div>
      <h3 style={headingStyle}>{topic.title}</h3>

      <div style={docBlockStyle}>
        {userBullets.length > 0 && (
          <>
            <h4 style={subheadingStyle}>What this does (user perspective)</h4>
            <ul style={listStyle}>
              {userBullets.map((b, i) => (
                <li key={`u-${i}`}>{b}</li>
              ))}
            </ul>
          </>
        )}

        {techBullets.length > 0 && (
          <>
            <h4 style={subheadingStyle}>Technical details</h4>
            <ul style={listStyle}>
              {techBullets.map((b, i) => (
                <li key={`t-${i}`}>{b}</li>
              ))}
            </ul>
          </>
        )}

        {userBullets.length === 0 && techBullets.length === 0 && topic.short_desc && (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            {topic.short_desc}
          </div>
        )}
      </div>

      {action}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const columnStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  minWidth: 0,
};

const headingStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: 'var(--text-primary)',
  marginBottom: 10,
};

const subheadingStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-secondary)',
  marginBottom: 4,
  marginTop: 10,
};

const docBlockStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  padding: 12,
  marginBottom: 12,
  fontSize: 12,
  lineHeight: 1.6,
  color: 'var(--text-secondary)',
};

const listStyle: React.CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
};

const utilityButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: 'var(--text-accent)',
  border: '1px solid var(--text-accent)',
  borderRadius: 4,
  padding: '6px 14px',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
};

const warningButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: 'var(--warning)',
  border: '1px solid var(--warning)',
  borderRadius: 4,
  padding: '6px 14px',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
};

const dangerButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: 'var(--error)',
  border: '1px solid var(--error)',
  borderRadius: 4,
  padding: '6px 14px',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
};
