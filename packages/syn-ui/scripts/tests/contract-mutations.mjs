#!/usr/bin/env node
// Mutation proof for the Skyline contract gates (PR #1764, codex verifier
// report). Each case applies the verifier's exact mutation, runs the gate that
// must now catch it, asserts a non-zero exit, prints the first error line, and
// restores the file byte for byte (also on failure or Ctrl-C).
//
//   node packages/syn-ui/scripts/tests/contract-mutations.mjs [case-id...]
//
// Not part of `just skyline-check` (it runs svelte-check several times and
// edits files in place); run it after touching a gate: `just skyline-mutations`.
import { readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = join(dirname(fileURLToPath(import.meta.url)), '../../../..')
const r = (p) => join(repo, p)
const contracts = () =>
  realpathSync(r('packages/syn-ui/skyline-core/node_modules/@syntropic137/design-contracts'))

const CASES = [
  {
    id: 'upstream-size-xl',
    gap: 1,
    what: 'widen ComponentSize with "xl" in the installed button contract',
    file: () => join(contracts(), 'dist/components/button.d.ts'),
    apply: (s) => s.replace('size?: ComponentSize;', 'size?: ComponentSize | "xl";'),
    cmd: 'pnpm --filter @syn137/skyline-svelte-v5 run typecheck',
  },
  {
    id: 'upstream-tone-info',
    gap: 1,
    what: 'widen ComponentTone with "info" upstream (equality still holds; the lookups must not)',
    file: () => join(contracts(), 'dist/shared.d.ts'),
    apply: (s) => s.replace('"danger" | "accent";', '"danger" | "accent" | "info";'),
    cmd: 'pnpm --filter @syn137/skyline-svelte-v5 run typecheck',
  },
  {
    id: 'badge-variant-build',
    gap: 2,
    what: "add variant?: 'broken' to BadgeProps, then build the app",
    file: () => r('packages/syn-ui/skyline-svelte-v5/src/components/Badge/types.ts'),
    apply: (s) => s.replace('  size?: Exclude<ContractSize', "  variant?: 'broken'\n  size?: Exclude<ContractSize"),
    cmd: 'pnpm --filter syn-ui run build',
  },
  {
    id: 'button-drop-loading',
    gap: 3,
    what: "drop the contract prop `loading` from Button.svelte (verifier's drift.cjs mutation)",
    file: () => r('packages/syn-ui/skyline-svelte-v5/src/components/Button/Button.svelte'),
    apply: (s) =>
      s
        .replace(': ButtonProps = $props()', ": Omit<ButtonProps, 'loading'> = $props()")
        .replace('    loading = false,\n', '')
        .replace('  // Upstream variant', '  const loading = false\n\n  // Upstream variant'),
    cmd: 'just skyline-verify-contracts',
  },
  {
    id: 'button-drop-type',
    gap: 3,
    what: 'drop the contract prop `type` from Button.svelte (app svelte-check missed this one)',
    file: () => r('packages/syn-ui/skyline-svelte-v5/src/components/Button/Button.svelte'),
    apply: (s) =>
      s
        .replace(': ButtonProps = $props()', ": Omit<ButtonProps, 'type'> = $props()")
        .replace("    type = 'button',\n", '')
        .replace('  // Upstream variant', "  const type = 'button'\n\n  // Upstream variant"),
    cmd: 'just skyline-verify-contracts',
  },
  {
    id: 'themes-drop-control',
    gap: 4,
    what: 'remove --sky-color-control from both themes',
    files: () => [r('packages/syn-ui/themes/src/skyline.css'), r('packages/syn-ui/themes/src/syn137.css')],
    apply: (s) => s.replace(/^.*--sky-color-control:.*\n/m, ''),
    cmd: 'pnpm --filter @syn137/skyline-themes run check',
  },
  {
    id: 'motion-unguarded-keyframes',
    gap: 5,
    what: 'add a @keyframes to motion.css outside the reduced-motion guard',
    file: () => r('packages/syn-ui/themes/src/motion.css'),
    apply: (s) => `${s}\n@keyframes sky-unguarded { from { opacity: 0; } }\n`,
    cmd: 'pnpm --filter @syn137/skyline-themes run check',
  },
  {
    id: 'motion-unguarded-animation',
    gap: 5,
    what: 'play an animation from motion.css outside the reduced-motion guard',
    file: () => r('packages/syn-ui/themes/src/motion.css'),
    apply: (s) => s.replace('  vertical-align: bottom;\n}', '  vertical-align: bottom;\n  animation: sky-type 1.8s both;\n}'),
    cmd: 'pnpm --filter @syn137/skyline-themes run check',
  },
  {
    id: 'motion-infinite',
    gap: 5,
    what: 'make the caret blink forever',
    file: () => r('packages/syn-ui/themes/src/motion.css'),
    apply: (s) => s.replace('sky-blink 1s steps(1) 20;', 'sky-blink 1s steps(1) infinite;'),
    cmd: 'pnpm --filter @syn137/skyline-themes run check',
  },
  {
    id: 'motion-colour-literal',
    gap: 5,
    what: 'hard-code the flash colour in motion.css',
    file: () => r('packages/syn-ui/themes/src/motion.css'),
    apply: (s) => s.replace('drop-shadow(0 0 10px var(--ds-color-danger))', 'drop-shadow(0 0 10px #FF6F61)'),
    cmd: 'pnpm --filter @syn137/skyline-themes run check',
  },
]

const only = process.argv.slice(2)
let bad = 0
for (const c of CASES.filter((c) => only.length === 0 || only.includes(c.id))) {
  const paths = c.files ? c.files() : [c.file()]
  const saved = paths.map((p) => [p, readFileSync(p)])
  const restore = () => saved.forEach(([p, b]) => writeFileSync(p, b))
  process.once('SIGINT', () => (restore(), process.exit(130)))
  try {
    for (const [p, b] of saved) {
      const next = c.apply(b.toString('utf8'))
      if (next === b.toString('utf8')) throw new Error(`mutation did not apply to ${p}`)
      writeFileSync(p, next)
    }
    const res = spawnSync(c.cmd, { cwd: repo, shell: true, encoding: 'utf8' })
    const out = `${res.stdout}\n${res.stderr}`.replace(/\x1b\[[0-9;]*m/g, '')
    const lines = out.split('\n')
    const first =
      [/not defined in|matches no defined|outside @media|infinite animation|colour literal/, / ERROR "|error TS\d+/, /✗/, /Error: /, /FAIL/]
        .map((re) => lines.find((l) => re.test(l) && !/ERR_PNPM|ELIFECYCLE|\$ /.test(l)))
        .find(Boolean)
        ?.trim()
        .slice(0, 400) ?? '(no error line)'
    if (res.status === 0) {
      console.error(`FAIL gap ${c.gap} ${c.id}: \`${c.cmd}\` exited 0 with the mutation applied (${c.what})`)
      bad++
    } else {
      console.log(`ok   gap ${c.gap} ${c.id}: \`${c.cmd}\` exited ${res.status}\n       ${first}`)
    }
  } finally {
    restore()
  }
}
process.exit(bad ? 1 : 0)
