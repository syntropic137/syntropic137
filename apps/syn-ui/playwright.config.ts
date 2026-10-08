/**
 * Shared Playwright suite (e2e/). The same specs run against syn-ui and the
 * React dashboard by switching the base URL (spec, Migration plan).
 *
 *   Default: starts syn-ui in fixtures mode on E2E_PORT (5199) and tests it.
 *   React:   E2E_TARGET=react E2E_BASE_URL=http://127.0.0.1:5173/ playwright test
 *   /next:   E2E_BASE_URL=http://host/next/ playwright test
 *
 * See e2e/support/env.ts for every variable.
 */
import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'
import { BASE_URL, E2E_PORT, startsOwnServer } from './e2e/support/env'

// Use the preinstalled Chromium when Playwright's own build is not there.
const CHROMIUM = process.env.PW_CHROMIUM_PATH ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined)

const desktop = { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } }
const phone = { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true }

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  outputDir: './e2e/.results',
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never', outputFolder: './e2e/.report' }]] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Never send the app's own traffic through an outbound HTTP(S)_PROXY.
    launchOptions: { ...(CHROMIUM ? { executablePath: CHROMIUM } : {}), args: ['--proxy-bypass-list=127.0.0.1;localhost;[::1]'] },
  },
  projects: [
    { name: 'desktop', use: desktop, testIgnore: '**/phone.spec.ts' },
    { name: 'phone', use: phone, testMatch: '**/phone.spec.ts' },
  ],
  webServer: startsOwnServer
    ? {
        command: `pnpm exec vite --port ${E2E_PORT} --strictPort --host 127.0.0.1`,
        cwd: import.meta.dirname,
        url: BASE_URL,
        env: { VITE_SYN_FIXTURES: '1' },
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
        stdout: 'ignore',
        stderr: 'pipe',
      }
    : undefined,
})
