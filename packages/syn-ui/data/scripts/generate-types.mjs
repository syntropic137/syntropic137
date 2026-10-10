#!/usr/bin/env node
// Regenerate src/generated/api-types.ts from the API's OpenAPI spec, the same
// source apps/syn-dashboard-ui and apps/syn-cli-node generate from.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
// An explicit spec path (first argument) regenerates from another committed spec,
// e.g. main's while this branch's API lags it.
const input = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(here, '../../../../apps/syn-docs/openapi.json')
const output = path.resolve(here, '../src/generated/api-types.ts')

if (!fs.existsSync(input)) {
  console.error(`OpenAPI spec not found at ${input}`)
  process.exit(1)
}
const ast = await openapiTS(new URL(`file://${input}`))
const header = '// @generated -- do not edit. Regenerate with: pnpm --filter @syn137/syn-ui-data generate:types\n\n'
fs.writeFileSync(output, header + astToString(ast), 'utf-8')
console.log(`Generated ${output}`)
