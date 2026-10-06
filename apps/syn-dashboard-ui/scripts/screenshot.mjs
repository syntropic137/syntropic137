#!/usr/bin/env node
// Full-page screenshot of a URL with headless Chromium.
//
//   node scripts/screenshot.mjs <url> <out.png> [--viewport WxH] [--fixtures <file.json>] [--expand]
//
// --fixtures answers API calls from a JSON file instead of a server, so a page
// can be shot with data where no API is reachable. The file maps a request
// pathname ("/api/v1/workflows/wf-1") to the JSON body to return; any other
// /api/ request gets a 404, as an unknown resource would. --expand opens every
// <details> before the shot, so collapsed content can be seen.
//
// Uses the Playwright that is installed globally, NOT a project dependency:
// the agent workspace image bakes Playwright 1.63.0 together with its matching
// headless Chromium (offline, at $PLAYWRIGHT_BROWSERS_PATH). A Playwright
// pinned here at any other version would look for a browser that is not there.
// See README.md "Screenshots for UI verification".

import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const USAGE = 'usage: screenshot.mjs <url> <out.png> [--viewport WxH] [--fixtures <file.json>] [--expand]'
const DEFAULT_VIEWPORT = { width: 1280, height: 800 }

function fail(message) {
  console.error(`screenshot: ${message}`)
  process.exit(2)
}

function parseArgs(argv) {
  const positional = []
  let viewport = DEFAULT_VIEWPORT
  let fixtures = null
  let expand = false
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--viewport') {
      // Zero is rejected here: Chromium either hangs on it or silently renders a
      // degenerate page (0x0 has produced a 32x480 PNG), neither a UI check.
      const match = /^([1-9]\d*)x([1-9]\d*)$/.exec(argv[++i] ?? '')
      if (!match) fail(`--viewport expects positive WxH, e.g. 1440x900\n${USAGE}`)
      viewport = { width: Number(match[1]), height: Number(match[2]) }
    } else if (argv[i] === '--expand') {
      expand = true
    } else if (argv[i] === '--fixtures') {
      const file = argv[++i]
      if (!file) fail(`--fixtures expects a JSON file\n${USAGE}`)
      fixtures = JSON.parse(readFileSync(file, 'utf8'))
    } else {
      positional.push(argv[i])
    }
  }
  if (positional.length !== 2) fail(USAGE)
  const [url, out] = positional
  return { url, out, viewport, fixtures, expand }
}

async function loadGlobalPlaywright() {
  const root = execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim()
  const entry = join(root, 'playwright', 'index.mjs')
  if (!existsSync(entry)) {
    fail(
      `no global Playwright at ${entry}. Outside the agent workspace image, ` +
        'install it with: npm i -g playwright@1.63.0 && playwright install chromium',
    )
  }
  return import(pathToFileURL(entry).href)
}

const { url, out, viewport, fixtures, expand } = parseArgs(process.argv.slice(2))
const { chromium } = await loadGlobalPlaywright()

const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport })
  if (fixtures) {
    await page.route('**/api/**', (route) => {
      const { pathname } = new URL(route.request().url())
      const body = fixtures[pathname]
      return body === undefined
        ? route.fulfill({ status: 404, json: { detail: `no fixture for ${pathname}` } })
        : route.fulfill({ status: 200, json: body })
    })
  }
  // The dashboard polls its API; with no API reachable the network never goes
  // idle, so wait for the load event and give the app a moment to render.
  const response = await page.goto(url, { waitUntil: 'load' })
  await page.waitForTimeout(1500)
  if (expand) {
    await page.evaluate(() => document.querySelectorAll('details').forEach((d) => { d.open = true }))
  }
  const png = await page.screenshot({ path: out, fullPage: true })
  // Width and height are big-endian u32s in the PNG IHDR chunk.
  const width = png.readUInt32BE(16)
  const height = png.readUInt32BE(20)
  console.log(
    `screenshot: ${out} ${width}x${height} ${png.length} bytes, ` +
      `HTTP ${response?.status() ?? 'n/a'}, title ${JSON.stringify(await page.title())}`,
  )
  // goto() resolves for HTTP errors too. Keep the screenshot as a diagnostic,
  // but a missing route must not pass as a verified one.
  if (response && !response.ok()) {
    console.error(`screenshot: ${url} returned HTTP ${response.status()}`)
    process.exitCode = 1
  }
} finally {
  await browser.close()
}
