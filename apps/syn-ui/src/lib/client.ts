/**
 * The app's one client setup (ADR-074 binding layer): fixtures or the live
 * API. main.ts calls this, so the composition root never imports the data
 * package itself.
 */
import { configureClient } from '@syn137/syn-ui-data'

export function startClient(fixtures: boolean): void {
  configureClient({ fixtures })
}
