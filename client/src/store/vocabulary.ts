// ---------------------------------------------------------------------------
// vocabulary -- the run's bound vocabulary, and comparing through it
// ---------------------------------------------------------------------------
//
// The engine owns *roles* (`bridge_type.top`, `event_type.answer_found`, ...); the run's
// configuration binds each role to the name of an enum-table row. The server publishes the
// bindings once per run, with the run itself (`vocabulary`, and `link_behaviours`: each
// link type's name -> its behaviour). A display compares the names it receives through
// this module and never against a literal name, so renaming a bound row in the
// configuration cannot break a display.
//
// A role nothing binds reads as a string no real name can equal (`v('x')` is never the
// empty string, nor any name the server sends), so a comparison against it is false and
// nothing crashes. A link type the server did not describe has no behaviour (null).
//
// Run statuses (`running`, `answer_found` as a status ...) are not vocabulary.
// ---------------------------------------------------------------------------

import { create } from 'zustand';

/** What the server sends with a run (`RunResponse`, a recorded run's summary). */
export interface VocabularyPayload {
  vocabulary?: Record<string, string> | null;
  link_behaviours?: Record<string, string | null> | null;
}

interface VocabularyState {
  vocabulary: Record<string, string>;
  linkBehaviours: Record<string, string | null>;
  /** Adopt a run's payload. A response that carries none leaves the current one alone. */
  adopt: (payload: VocabularyPayload | null | undefined) => void;
  /** Forget everything: every role unbound. */
  clear: () => void;
}

export const useVocabularyStore = create<VocabularyState>((set) => ({
  vocabulary: {},
  linkBehaviours: {},
  adopt: (payload) => {
    if (!payload || (!payload.vocabulary && !payload.link_behaviours)) return;
    set({
      vocabulary: { ...(payload.vocabulary ?? {}) },
      linkBehaviours: { ...(payload.link_behaviours ?? {}) },
    });
  },
  clear: () => set({ vocabulary: {}, linkBehaviours: {} }),
}));

/** The value of an unbound role: a string that equals no name the server sends. */
export function unboundName(role: string): string {
  return `\u0000unbound:${role}`;
}

/** The name bound to `role` in a vocabulary map, or the unbound value. */
function nameIn(vocabulary: Record<string, string>, role: string): string {
  return Object.prototype.hasOwnProperty.call(vocabulary, role)
    ? vocabulary[role]
    : unboundName(role);
}

export type RoleName = (role: string) => string;

/** The name bound to `role` right now (outside React). */
export const v: RoleName = (role) => nameIn(useVocabularyStore.getState().vocabulary, role);

/** The same, subscribed: the component re-renders when another run's vocabulary arrives. */
export function useVocabulary(): RoleName {
  const vocabulary = useVocabularyStore((s) => s.vocabulary);
  return (role) => nameIn(vocabulary, role);
}

/** The behaviour of a link type (`category`, `instance`, `property`, `lateral`, `slip`), or null. */
export type LinkBehaviourOf = (linkType: string) => string | null;

function behaviourIn(map: Record<string, string | null>, linkType: string): string | null {
  return Object.prototype.hasOwnProperty.call(map, linkType) ? map[linkType] : null;
}

/** The behaviour of a link type right now (outside React). */
export const behaviourOf: LinkBehaviourOf = (t) =>
  behaviourIn(useVocabularyStore.getState().linkBehaviours, t);

/** Subscribed: the link behaviours, so a display compares links by behaviour. */
export function useLinkBehaviours(): {
  behaviourOf: LinkBehaviourOf;
  /** The link types the run's configuration has, in the server's order. */
  linkTypes: string[];
} {
  const map = useVocabularyStore((s) => s.linkBehaviours);
  return { behaviourOf: (t) => behaviourIn(map, t), linkTypes: Object.keys(map) };
}
