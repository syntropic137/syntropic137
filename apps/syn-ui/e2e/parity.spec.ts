/**
 * Value parity with the React dashboard (scratchpad parity report,
 * 2026-10-09): each case pins a value the Svelte UI got wrong against the
 * fixture world, whose shapes mirror the live API.
 */
import { expect, test } from './support/test'
import { isFixtures, isSkyline } from './support/env'
import { FIXTURE_IDS } from './support/routes'

test.skip(!isSkyline || !isFixtures, 'pins fixture values on syn-ui')

test('Overview Live commits lists commits from /events/recent, nested agent shape included', async ({ page }) => {
  await page.goto('./')
  const commits = page.getByRole('region', { name: 'Live commits' })
  await expect(commits.getByText('922a6b2')).toBeVisible()
  await expect(commits.getByText(/member-access specifier/)).toBeVisible()
  await expect(commits.getByText(/No git events yet/)).toHaveCount(0)
})

test('Workflow detail recent runs read the Executions list usage, failed phases included (#1843)', async ({ page }) => {
  await page.goto('./workflows/skills-matrix')
  const runs = page.locator('section', { has: page.getByRole('heading', { name: 'Recent runs' }) })
  // The failed run: 92,500 tokens on Executions; /runs alone would say 69.4k.
  await expect(runs.getByText('92.5k')).toBeVisible()
  await expect(runs.getByText('69.4k')).toHaveCount(0)
})

test('Workflow detail shows per-phase tokens and cost, sessions and artifacts (from /metrics?workflow_id=)', async ({ page }) => {
  await page.goto('./workflows/research-workflow')
  const main = page.locator('#sky-main')
  await expect(main.getByText('Sessions', { exact: true })).toBeVisible()
  await expect(main.getByText('Artifacts', { exact: true })).toBeVisible()
  await expect(main.getByText(/tok · \d+%/).first()).toBeVisible()
  // The fixture's running Research run: its phase cost still accrues.
  await expect(main.getByText(/^≥\$/).first()).toBeVisible()
})

test('Evals board cells show the latest run cost beside the latest verdict', async ({ page }) => {
  await page.goto('./evals')
  // shared-esp-stream under sonnet: runs $0.4963 (latest, PASS) and $0.4711; the median, shown before, is $0.48.
  const cell = page.locator('[data-cell="shared-esp-stream:eval-verify-pinned-sonnet-v1"]')
  await expect(cell).toHaveAttribute('aria-label', /: Pass, \$0\.50$/)
})

test('Eval detail "Same case, other verifiers" pairs each verifier with its own last verdict', async ({ page }) => {
  await page.goto('./evals/eval-stable-shared-esp-stream')
  const section = page.locator('section', { has: page.getByRole('heading', { name: /Same case/ }) })
  // The stable eval's last verdict is Pass, but its sdlc-lean verifier failed and sdlc-baseline errored.
  await expect(section.getByRole('link', { name: /: Fail$/ })).toHaveCount(1)
  await expect(section.getByRole('link', { name: /: Error$/ })).toHaveCount(1)
})

test('Artifacts cards name the phase that wrote the file, never an ordinal "phase NN"', async ({ page }) => {
  await page.goto('./artifacts')
  const cards = page.locator('#sky-main li[data-sky-row]')
  await expect(cards.first()).toBeVisible()
  await expect(page.locator('#sky-main').getByText(/^phase \d+$/)).toHaveCount(0)
  // Every artifact row in the fixtures (and the API) carries a phase_id; the card prints it.
  const texts = await cards.allInnerTexts()
  expect(texts.some((t) => /\n(research|synthesize|report|review|plan|implement|summarize)\b/i.test(`\n${t}`))).toBe(true)
})

test('Executions shows a correct refusal as Refused, not Failed', async ({ page }) => {
  await page.goto('./executions?window=all&status=failed')
  const main = page.locator('#sky-main')
  await expect(main.getByRole('link', { name: /, Refused, started/ })).toHaveCount(1)
  await expect(main.getByRole('link', { name: /, Failed, started/ }).first()).toBeVisible()
})

test('Execution detail has a Cost by model block beside cost by phase', async ({ page }) => {
  await page.goto(`./executions/${FIXTURE_IDS.execution}`)
  const usage = page.getByRole('region', { name: 'Usage' })
  await expect(usage.getByText('Cost by phase')).toBeVisible()
  await expect(usage.getByText('Cost by model')).toBeVisible()
})
