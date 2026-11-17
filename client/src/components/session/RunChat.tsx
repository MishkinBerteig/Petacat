// ---------------------------------------------------------------------------
// Petacat -- Training Mode Sessions: the chat of one multi-turn run
// ---------------------------------------------------------------------------
//
// A multi-turn run is a chat. Each turn is one engine run on the four positions of a
// context-response analogy problem, and reads like a message and its reply: the Context line
// shows the 1st, 2nd and 3rd positions side by side, and the Response is the 4th, which
// Petacat constructs. The next turn's 1st position is the previous turn's three context
// strings joined with single spaces, its 2nd is the previous response, and its 3rd is what
// the teacher gives. So the conversation reads as a context history that grows turn by turn.
// The run's state and its Close chat button are on its row in the runs table, not here; the chat
// tells its row (`onChange`) as soon as the run's state or turn count changes, so the row keeps up.
//
// The chat polls `GET .../runs/{seed}` while it is open and the run is not ended (no
// push channel), and sends the teacher's input or end through `POST .../input`.
// Strings are shown exactly as given: never trimmed, collapsed or normalised.
// ---------------------------------------------------------------------------

import { useRef, useState, type ReactNode } from 'react';
import { ApiError, describeApiError, getSessionConversation, supplySessionInput } from '@/api/client';
import type { SessionConversation, SessionPositionSource, SessionRunEndReason, SessionTurn } from '@/types';
import { checkString } from './problemText';
import { ControlHelp, IDLE_POLL_MS, RUNNING_POLL_MS, errorStyle, fmtInt, usePolling } from './shared';

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

/** The same, naming the turn that ended the run (the runs table): "turn 2 had no answer". */
const END_REASON_AT: Partial<Record<SessionRunEndReason, (turn: number) => string>> = {
  'no-answer': (n) => `turn ${n} had no answer`,
  teacher: (n) => `the teacher ended it after turn ${n}`,
  error: (n) => `an error in turn ${n}`,
};

/**
 * "a turn with no answer" or "the teacher ended it (label: ...)"; given the number of the run's
 * last turn, the reasons that happen at a turn name it: "turn 2 had no answer".
 */
export function endText(reason: SessionRunEndReason | null, label: string | null, lastTurn?: number): string {
  if (reason === null) return '';
  const at = lastTurn !== undefined && lastTurn > 0 ? END_REASON_AT[reason] : undefined;
  return `${at ? at(lastTurn!) : END_REASON[reason]}${label ? ` (label: ${label})` : ''}`;
}

const SOURCE: Record<SessionPositionSource, string> = {
  problem: 'the problem',
  window: 'the window',
  teacher: 'the teacher',
  petacat: 'Petacat',
};

type Position = 'context' | 'second' | 'input' | 'response';

/** Where a position's string came from, for a turn: the problem, the turn before, the teacher or Petacat. */
function whereFrom(position: Position, t: SessionTurn): string {
  const by = t.supplied_by[position];
  if (by === 'window' && t.turn > 1) {
    const prev = t.turn - 1;
    if (position === 'context') return `turn ${prev}'s context, joined with single spaces`;
    if (position === 'second') return `turn ${prev}'s response`;
  }
  return SOURCE[by];
}

/** The positions the Context line shows, side by side: the 1st, 2nd and 3rd. */
const CONTEXT_POSITIONS: Position[] = ['context', 'second', 'input'];

/** One string of a turn, in a box that keeps its whitespace, with where it came from beneath it. */
function Part({ turn, position }: { turn: SessionTurn; position: Position }) {
  const value = turn.positions[position];
  const constructed = position === 'response';
  return (
    <div data-testid={`position-${position}`} style={{ minWidth: 0, maxWidth: '100%' }}>
      {value === null ? (
        <div className="text-xs text-muted" data-testid="no-response" style={{ padding: '1px 0' }}>
          {turn.status === 'pending'
            ? 'No response yet: this turn has not finished.'
            : 'No response: this turn did not answer.'}
        </div>
      ) : (
        <div
          className="mono"
          data-testid={`string-${position}`}
          style={{
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            border: `1px ${constructed ? 'solid' : 'dashed'} var(--border)`,
            borderRadius: 3,
            padding: '1px 6px',
            minHeight: '1.4em',
            minWidth: '1.5em',
            background: constructed ? 'var(--bg-panel)' : undefined,
          }}
        >
          {value}
        </div>
      )}
      <div className="text-xs text-muted" data-testid={`supplied-by-${position}`}>
        {whereFrom(position, turn)}
      </div>
      {value === '' && <div className="text-xs text-muted">(empty string)</div>}
      {value !== null && value !== '' && !PLAIN.test(value) && (
        <div className="text-xs text-muted mono" data-testid={`written-${position}`} style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
          as written: {asWritten(value)} ({characters(value)})
        </div>
      )}
    </div>
  );
}

/** A labelled line of a turn: "Context" with its three strings side by side, or "Response". */
function Line({ label, testId, children }: { label: string; testId: string; children: ReactNode }) {
  return (
    <div data-testid={testId} style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'flex-start' }}>
      <div className="text-xs" style={{ width: 70, flexShrink: 0, fontWeight: 700, paddingTop: 2 }}>
        {label}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, minWidth: 0, flex: 1, alignItems: 'flex-start' }}>
        {children}
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
        <div data-testid="turn-outcome">
          Status: <span data-testid="turn-status">{turn.status}</span> · {fmtInt(turn.codelets)} codelets
        </div>
        {turn.end_reason !== null && (
          <div data-testid="turn-end">Ended the run: {endText(turn.end_reason, turn.end_label)}</div>
        )}
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
        {turn.error && (
          <span style={{ color: 'var(--error)' }} data-testid="turn-error">
            Error: {turn.error}
          </span>
        )}
      </div>
      <Line label="Context" testId="turn-context">
        {CONTEXT_POSITIONS.map((p) => (
          <Part key={p} turn={turn} position={p} />
        ))}
      </Line>
      <Line label="Response" testId="turn-response">
        <Part turn={turn} position="response" />
      </Line>
      <Details turn={turn} />
    </div>
  );
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
  /** Called when the run's state or turn count changes while the chat is open (not on the first load). */
  onChange?: () => void;
}

export function RunChat({ sessionId, problemId, seed, onChange }: RunChatProps) {
  const [conv, setConv] = useState<SessionConversation | null>(null);
  // The state and turn count last shown, to tell the run's row when they change.
  const shown = useRef<string | null>(null);
  const take = (next: SessionConversation) => {
    const now = `${next.state}|${next.turn_count}`;
    if (shown.current !== null && shown.current !== now) onChange?.();
    shown.current = now;
    setConv(next);
  };
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      take(await getSessionConversation(sessionId, problemId, seed));
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
      take(await supplySessionInput(sessionId, problemId, seed, { turn: conv.waiting_for, ...input }));
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
      </div>
      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
      {!conv && !error && <div className="text-xs text-muted">Loading…</div>}
      {conv && (
        <>
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
                <ControlHelp topic="session_chat_end" label="End and its label" />
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
