/// <reference types="svelte" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves every request from @syn137/syn-ui-data fixtures (no backend). */
  readonly VITE_SYN_FIXTURES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
