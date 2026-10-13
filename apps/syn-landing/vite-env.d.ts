/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GITHUB_STARS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
