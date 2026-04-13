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
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
