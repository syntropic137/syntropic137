#!/usr/bin/env node
// Full-page screenshot of a URL with headless Chromium.
//
//   node scripts/screenshot.mjs <url> <out.png> [--viewport WxH]
//
// Uses the Playwright that is installed globally, NOT a project dependency:
// the agent workspace image bakes Playwright 1.63.0 together with its matching
// headless Chromium (offline, at $PLAYWRIGHT_BROWSERS_PATH). A Playwright
// pinned here at any other version would look for a browser that is not there.
// See README.md "Screenshots for UI verification".

import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const USAGE = 'usage: screenshot.mjs <url> <out.png> [--viewport WxH]'
const DEFAULT_VIEWPORT = { width: 1280, height: 800 }

function fail(message) {
  console.error(`screenshot: ${message}`)
  process.exit(2)
}

function parseArgs(argv) {
  const positional = []
  let viewport = DEFAULT_VIEWPORT
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--viewport') {
      const match = /^(\d+)x(\d+)$/.exec(argv[++i] ?? '')
      if (!match) fail(`--viewport expects WxH, e.g. 1440x900\n${USAGE}`)
      viewport = { width: Number(match[1]), height: Number(match[2]) }
    } else {
      positional.push(argv[i])
    }
  }
  if (positional.length !== 2) fail(USAGE)
  const [url, out] = positional
  return { url, out, viewport }
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

const { url, out, viewport } = parseArgs(process.argv.slice(2))
const { chromium } = await loadGlobalPlaywright()

const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport })
  // The dashboard polls its API; with no API reachable the network never goes
  // idle, so wait for the load event and give the app a moment to render.
  const response = await page.goto(url, { waitUntil: 'load' })
  await page.waitForTimeout(1500)
  const png = await page.screenshot({ path: out, fullPage: true })
  // Width and height are big-endian u32s in the PNG IHDR chunk.
  const width = png.readUInt32BE(16)
  const height = png.readUInt32BE(20)
  console.log(
    `screenshot: ${out} ${width}x${height} ${png.length} bytes, ` +
      `HTTP ${response?.status() ?? 'n/a'}, title ${JSON.stringify(await page.title())}`,
  )
} finally {
  await browser.close()
}
