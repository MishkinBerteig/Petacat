// ---------------------------------------------------------------------------
// Petacat -- Vitest global setup
// ---------------------------------------------------------------------------
//
// Loaded by vitest.config.ts before any test file. Its only job is to extend
// vitest's `expect` with the @testing-library/jest-dom matchers (e.g.
// toBeInTheDocument, toHaveTextContent) and install a cleanup hook that
// tears down any rendered React trees between tests.
// ---------------------------------------------------------------------------

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach } from 'vitest'

import { useVocabularyStore } from '@/store/vocabulary'

import { STANDARD_PAYLOAD } from './standardVocabulary'

// Node's own experimental `localStorage` shadows jsdom's and is `undefined` unless Node
// is given a storage file, so components that remember a choice per browser would
// otherwise run here without storage. An in-memory stand-in with the Storage surface
// they use; tests that want storage to fail replace it with their own.
if (typeof window.localStorage?.getItem !== 'function') {
  const data = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
      setItem: (k: string, v: string) => void data.set(k, String(v)),
      removeItem: (k: string) => void data.delete(k),
      clear: () => data.clear(),
    },
  })
}

// Every test starts with the Metacat Standard Configuration's bindings, as the server would
// have published them with the run; a test of another vocabulary adopts its own.
beforeEach(() => {
  useVocabularyStore.getState().clear()
  useVocabularyStore.getState().adopt(STANDARD_PAYLOAD)
})

afterEach(() => {
  cleanup()
})
