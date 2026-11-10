/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional direct API base URL; empty (the default) uses the Vite dev proxy. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
