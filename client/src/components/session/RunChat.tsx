// ---------------------------------------------------------------------------
// Petacat -- Training Mode Sessions: the chat of one multi-turn run
// ---------------------------------------------------------------------------
//
// A multi-turn run is a chat. Each turn is one engine run on the four positions of a
// context-response analogy problem: the context (1st position), the second string
// (2nd), the input (3rd) and the response (4th), which Petacat constructs. The next
// turn's context is the previous context, second string and input joined with single
// spaces; its second string is the previous response; its input is what the teacher
// gives. So the conversation reads as a context history that grows turn by turn.
//
// The chat polls `GET .../runs/{seed}` while it is open and the run is not ended (no
// push channel), and sends the teacher's input or end through `POST .../input`.
// Strings are shown exactly as given: never trimmed, collapsed or normalised.
// ---------------------------------------------------------------------------

import { useState } from 'react';
import { ApiError, describeApiError, getSessionConversation, supplySessionInput } from '@/api/client';
import type { SessionConversation, SessionPositionSource, SessionRunEndReason, SessionTurn } from '@/types';
import { checkString } from './problemText';
import { ControlHelp, IDLE_POLL_MS, RUNNING_POLL_MS, errorStyle, fmtInt, noticeStyle, usePolling } from './shared';

/** Plain words: letters, numbers, punctuation and symbols, single-spaced. Anything else gets an "as written" line. */
const PLAIN = /^[\p{L}\p{N}\p{P}\p{S}]+(?: [\p{L}\p{N}\p{P}\p{S}]+)*$/u;
/** Characters that look like nothing, or like another character, when drawn: shown by code in the "as written" line. */
const INVISIBLE = /[\p{M}\p{Cf}\p{Zs}\p{Zl}\p{Zp}]/gu;

/**
 * The string as a JSON string literal, with the marks and the spaces other than a plain space written
 * by code, so that a reader can see exactly what it holds (a tab as \t, a line break as \n).
 */
export function asWritten(s: string): string {
  return JSON.stringify(s).replace(INVISIBLE, (c) => {
    if (c === ' ') return c;
    const cp = c.codePointAt(0)!;
    return cp > 0xffff ? `\\u{${cp.toString(16)}}` : `\\u${cp.toString(16).padStart(4, '0')}`;
  });
}

const END_REASON: Record<SessionRunEndReason, string> = {
  'single-turn': 'its only turn',
  'no-answer': 'a turn with no answer',
  teacher: 'the teacher ended it',
  error: 'an error',
  cancelled: 'its problem was cancelled',
};

/** "no answer" or "the teacher ended it (label)". */
export function endText(reason: SessionRunEndReason | null, label: string | null): string {
  if (reason === null) return '';
  return `${END_REASON[reason]}${label ? ` (label: ${label})` : ''}`;
}

const SOURCE: Record<SessionPositionSource, string> = {
  problem: 'the problem',
  window: 'the window',
  teacher: 'the teacher',
  petacat: 'Petacat',
};

/** What a position holds, and where it came from, for a turn. */
function whereFrom(position: 'context' | 'second' | 'input' | 'response', t: SessionTurn): string {
  const by = t.supplied_by[position];
  if (by === 'window' && t.turn > 1) {
    const prev = t.turn - 1;
    if (position === 'context') {
      return `the window: turn ${prev}'s context, second string and input, joined with single spaces`;
    }
    if (position === 'second') return `the window: turn ${prev}'s response`;
  }
  return SOURCE[by];
}

const POSITIONS: { key: 'context' | 'second' | 'input' | 'response'; label: string; number: string }[] = [
  { key: 'context', label: 'Context', number: '1st' },
  { key: 'second', label: 'Second string', number: '2nd' },
  { key: 'input', label: 'Input', number: '3rd' },
  { key: 'response', label: 'Response', number: '4th' },
];

function Position({ turn, position }: { turn: SessionTurn; position: (typeof POSITIONS)[number] }) {
  const value = turn.positions[position.key];
  const constructed = position.key === 'response';
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 4, alignItems: 'flex-start' }} data-testid={`position-${position.key}`}>
      <div style={{ width: 118, flexShrink: 0 }} className="text-xs">
        <div style={{ fontWeight: 700 }}>{position.label}</div>
        <div className="text-muted" data-testid={`supplied-by-${position.key}`}>
          {position.number} · {whereFrom(position.key, turn)}
        </div>
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        {value === null ? (
          <div className="text-xs text-muted" data-testid="no-response">
            {turn.status === 'pending'
              ? 'No response yet: this turn has not finished.'
              : 'No response: this turn did not answer.'}
          </div>
        ) : (
          <>
            <div
              className="mono"
              data-testid={`string-${position.key}`}
              style={{
                display: 'block',
                whiteSpace: 'pre-wrap',
                overflowWrap: 'anywhere',
                border: `1px ${constructed ? 'solid' : 'dashed'} var(--border)`,
                borderRadius: 3,
                padding: '1px 4px',
                minHeight: '1.4em',
                background: constructed ? 'var(--bg-panel)' : undefined,
              }}
            >
              {value}
            </div>
            {value === '' && <div className="text-xs text-muted">(empty string)</div>}
            {!PLAIN.test(value) && value !== '' && (
              <div className="text-xs text-muted mono" data-testid={`written-${position.key}`} style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
                as written: {asWritten(value)} ({characters(value)})
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** "1 character", "2 characters": code points, as a person counts them. */
function characters(s: string): string {
  const n = [...s].length
  return `${fmtInt(n)} character${n === 1 ? '' : 's'}`
}

function countsText(c: Record<string, number>): string {
  const e = Object.entries(c);
  return e.length === 0 ? 'none' : e.map(([k, v]) => `${k} ${fmtInt(v)}`).join(', ');
}

function Details({ turn }: { turn: SessionTurn }) {
  const ev = turn.evidence;
  return (
    <details data-testid="turn-details" style={{ marginTop: 4 }}>
      <summary className="text-xs" style={{ cursor: 'pointer' }}>
        Details of turn {turn.turn}
      </summary>
      <div className="text-xs" style={{ marginTop: 4 }}>
        <div style={{ fontWeight: 700 }}>Evidence</div>
        {ev === null ? (
          <div className="text-muted" data-testid="no-evidence">
            No evidence: the turn has not finished.
          </div>
        ) : (
          <ul style={{ margin: '2px 0', paddingLeft: 16 }} data-testid="evidence">
            <li>Bonds by category: {countsText(ev.bonds)}</li>
            <li>Groups by category: {countsText(ev.groups)}</li>
            <li>
              Rule:{' '}
              {ev.rule === null ? 'none' : `${ev.rule.top_rule} (top); ${ev.rule.bottom_rule} (bottom)`}
            </li>
            <li>Snags: {ev.snags.length === 0 ? 'none' : ev.snags.join(', ')}</li>
            <li>Symbols still unperceived: {fmtInt(ev.unperceived)}</li>
            <li>
              Coderack pressure: {fmtInt(ev.coderack.full_posts)} full posts,{' '}
              {fmtInt(ev.coderack.overflowing_batches)} overflowing batches, {fmtInt(ev.coderack.evicted)} evicted
            </li>
          </ul>
        )}
        <div style={{ fontWeight: 700 }}>Proposals</div>
        <div data-testid="proposal-count">
          {turn.proposals.length === 0
            ? 'No proposals.'
            : `${fmtInt(turn.proposals.length)} proposal${turn.proposals.length === 1 ? '' : 's'}.`}
        </div>
        {turn.proposals.length > 0 && (
          <ul style={{ margin: '2px 0', paddingLeft: 16 }} data-testid="proposal-list">
            {turn.proposals.map((p, i) => (
              <li key={i} className="mono" style={{ overflowWrap: 'anywhere' }}>
                {JSON.stringify(p)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}

function TurnCard({ turn }: { turn: SessionTurn }) {
  return (
    <div
      data-testid="chat-turn"
      style={{ border: '1px solid var(--border)', borderRadius: 4, padding: 8, marginBottom: 8 }}
    >
      <div className="text-xs" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
        <strong>Turn {turn.turn}</strong>
        <span data-testid="turn-status">{turn.status}</span>
        <span>{fmtInt(turn.codelets)} codelets</span>
        {turn.end_reason !== null && (
          <span data-testid="turn-end">Ended the run: {endText(turn.end_reason, turn.end_label)}</span>
        )}
        {turn.error && (
          <span style={{ color: 'var(--error)' }} data-testid="turn-error">
            Error: {turn.error}
          </span>
        )}
      </div>
      {POSITIONS.map((p) => (
        <Position key={p.key} turn={turn} position={p} />
      ))}
      <Details turn={turn} />
    </div>
  );
}

/** The run's state, as the heading of the chat. */
export function stateText(c: SessionConversation): string {
  switch (c.state) {
    case 'running': {
      const last = c.turns[c.turns.length - 1];
      return `Running turn ${last ? last.turn : c.turn_count + 1}.`;
    }
    case 'waiting':
      return `Waiting for the input of turn ${c.waiting_for}.`;
    case 'ended':
      return `Ended: ${endText(c.end_reason, c.end_label) || 'no reason recorded'}.`;
    default:
      return 'Queued: nothing has run yet, or the next turn waits for the session to run.';
  }
}

/** Why the chat is not taking input although the run waits for it. */
function whyNoInput(c: SessionConversation): string {
  switch (c.session_state) {
    case 'stopped':
      return 'This Training Mode Session is Stopped: Start it, and then give the input.';
    case 'starting':
      return 'This Training Mode Session is Starting: it takes input when that finishes.';
    case 'stopping':
      return 'This Training Mode Session is Stopping: it takes input when that finishes.';
    default:
      return `This Training Mode Session is ${c.session_state}: the server is not taking input for this run now.`;
  }
}

/** One sentence for a failed Send or End: a `stale`, a `busy`, a 422 or anything else, with the server's words. */
export function describeInputError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail;
    if (err.status === 409 && detail.startsWith('stale')) {
      return `Not taken, because the run has moved on (it is not waiting for that turn's input any more): ${detail} The chat is refreshed.`;
    }
    if (err.status === 409 && detail.startsWith('busy')) {
      return `Not taken, because the Training Mode Session is busy: ${detail}`;
    }
    if (err.status === 422) {
      return `Not taken, because the input was refused as text (HTTP 422): ${detail}`;
    }
  }
  return describeApiError(err, 'send the input');
}

export interface RunChatProps {
  sessionId: number;
  problemId: number;
  seed: number;
  onClose: () => void;
}

export function RunChat({ sessionId, problemId, seed, onClose }: RunChatProps) {
  const [conv, setConv] = useState<SessionConversation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setConv(await getSessionConversation(sessionId, problemId, seed));
      setError(null);
    } catch (err) {
      setError(describeApiError(err, 'load the chat'));
    }
  };

  // While the chat is open and the run is not ended: at the session's cadences, quicker while a turn runs.
  // The first fetch has no state yet and takes the quicker one; an ended run is fetched once.
  const ended = conv?.state === 'ended';
  const interval = ended ? null : conv && conv.state !== 'running' ? IDLE_POLL_MS : RUNNING_POLL_MS;
  usePolling(refresh, interval, `${sessionId}|${problemId}|${seed}`);

  const waiting = conv?.state === 'waiting' && conv.waiting_for !== null;
  const textProblem = checkString('the input', text);

  const send = async (input: { text: string } | { end: true; label?: string }) => {
    if (!conv || conv.waiting_for === null) return;
    setBusy(true);
    setSendError(null);
    try {
      const next = await supplySessionInput(sessionId, problemId, seed, { turn: conv.waiting_for, ...input });
      setConv(next);
      setText('');
      setLabel('');
    } catch (err) {
      setSendError(describeInputError(err));
      if (err instanceof ApiError && err.status === 409 && err.detail.startsWith('stale')) await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="run-chat" style={{ marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <strong className="text-sm">
          Chat of seed {seed}
        </strong>
        <ControlHelp topic="session_chat" label="the chat" />
        <span style={{ flex: 1 }} />
        <button type="button" onClick={onClose}>
          Close chat
        </button>
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {!conv && !error && <div className="text-xs text-muted">Loading…</div>}
      {conv && (
        <>
          <div
            role="status"
            data-testid="chat-state"
            style={{
              ...noticeStyle,
              marginBottom: 6,
              fontWeight: 700,
              borderColor: conv.state === 'waiting' ? 'var(--warning)' : undefined,
            }}
          >
            {stateText(conv)}
          </div>
          {conv.turns.map((t) => (
            <TurnCard key={t.turn} turn={t} />
          ))}
          {waiting && !conv.accepts_input && (
            <div className="text-xs" role="note" data-testid="no-input-reason" style={{ marginBottom: 6 }}>
              {whyNoInput(conv)}
            </div>
          )}
          {waiting && conv.accepts_input && (
            <div data-testid="chat-input" style={{ border: '1px solid var(--warning)', borderRadius: 4, padding: 8 }}>
              <label htmlFor={`chat-input-${seed}`} className="text-xs" style={{ fontWeight: 700 }}>
                Input for turn {conv.waiting_for}
              </label>
              <textarea
                id={`chat-input-${seed}`}
                value={text}
                rows={2}
                disabled={busy}
                spellCheck={false}
                onChange={(e) => setText(e.target.value)}
                style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: 12, boxSizing: 'border-box' }}
              />
              {text !== '' && textProblem && (
                <div className="text-xs" role="note" data-testid="chat-input-problem" style={{ color: 'var(--error)' }}>
                  {textProblem}
                </div>
              )}
              <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                <button type="button" disabled={busy || textProblem !== null} onClick={() => void send({ text })}>
                  Send
                </button>
                <span style={{ flex: 1 }} />
                <label htmlFor={`chat-end-label-${seed}`} className="text-xs">
                  End label (optional)
                </label>
                <input
                  id={`chat-end-label-${seed}`}
                  type="text"
                  value={label}
                  disabled={busy}
                  onChange={(e) => setLabel(e.target.value)}
                  style={{ width: 140 }}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void send(label === '' ? { end: true } : { end: true, label })}
                >
                  End
                </button>
              </div>
            </div>
          )}
          {sendError && (
            <div role="alert" data-testid="chat-send-error" style={{ ...errorStyle, marginTop: 6 }}>
              {sendError}
            </div>
          )}
        </>
      )}
    </div>
  );
}
