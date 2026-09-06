import { defineConfig } from '@playwright/test'
import { liveBackendEnv } from './tests/live-test-env'

export default defineConfig({
  testDir: './tests',
  testMatch: 'live.spec.ts',
  timeout: 90000,
  expect: { timeout: 15000 },
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'test-results/live-results.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:5175',
    browserName: 'chromium',
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'node scripts/start-live-backend.cjs',
      url: 'http://127.0.0.1:8001/health',
      env: liveBackendEnv,
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5175 --strictPort',
      url: 'http://127.0.0.1:5175',
      env: { VITE_DEMO_MODE: 'false', VITE_API_PROXY_TARGET: 'http://127.0.0.1:8001' },
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
})
