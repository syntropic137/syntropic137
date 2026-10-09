/// <reference types="svelte" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves every request from @syn137/syn-ui-data fixtures (no backend). */
  readonly VITE_SYN_FIXTURES?: string
}

/** apps/syn-ui/package.json `version`, injected by vite.config.ts. */
declare const __SYN_UI_VERSION__: string

interface ImportMeta {
  readonly env: ImportMetaEnv
}
