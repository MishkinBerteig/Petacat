/// <reference types="vitest" />
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

// Reuse the production Vite config (so the `@/` alias and React plugin are
// both picked up automatically) and layer test-specific settings on top.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: false,
      setupFiles: ['./src/test/setup.ts'],
      // Match *.test.tsx / *.test.ts next to source files.
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
)
