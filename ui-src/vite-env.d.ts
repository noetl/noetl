/// <reference types="vite/client" />

declare global {
  interface ImportMetaEnv {
    readonly VITE_API_BASE_URL?: string;
  }
}
