/// <reference types="vite/client" />

declare global {
  interface ImportMetaEnv {
    readonly VITE_GATEWAY_URL?: string;
    readonly VITE_AUTH0_DOMAIN?: string;
    readonly VITE_AUTH0_CLIENT_ID?: string;
    readonly VITE_AUTH0_REDIRECT_URI?: string;
  }
}
