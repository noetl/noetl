import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const defaultTarget = 'https://gateway.mestumre.dev';
  const rawTarget = (env.VITE_GATEWAY_URL || defaultTarget).trim();
  const withScheme = /^https?:\/\//i.test(rawTarget) ? rawTarget : `https://${rawTarget}`;

  let gatewayTarget = defaultTarget;
  try {
    const parsed = new URL(withScheme);
    const isLocalLoop =
      (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') &&
      (!parsed.port || parsed.port === '8080');

    gatewayTarget = isLocalLoop ? defaultTarget : `${parsed.protocol}//${parsed.host}`;

    if (isLocalLoop) {
      console.warn(
        `[gateway-react-amadeus-example] Ignoring VITE_GATEWAY_URL=${rawTarget} to prevent proxy loop. Using ${defaultTarget}`
      );
    }
  } catch (error) {
    console.warn(
      `[gateway-react-amadeus-example] Invalid VITE_GATEWAY_URL=${rawTarget}. Using ${defaultTarget}`,
      error
    );
    gatewayTarget = defaultTarget;
  }

  console.log(`[gateway-react-amadeus-example] Proxy target: ${gatewayTarget}`);

  function proxyOptions() {
    return {
      target: gatewayTarget,
      changeOrigin: true,
      // Dev fixture: allow proxying through environments with custom TLS chains.
      secure: false,
      configure(proxy, options) {
        proxy.on('error', (error, req) => {
          const method = req?.method || 'UNKNOWN';
          const url = req?.url || '';
          console.error(
            `[gateway-react-amadeus-example] Proxy error for ${method} ${url} -> ${options.target}:`,
            error?.message || error
          );
        });
      },
    };
  }

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 8080,
      proxy: {
        '/health': proxyOptions(),
        '/api': proxyOptions(),
        '/graphql': proxyOptions(),
        '/noetl': proxyOptions(),
        '/events': proxyOptions(),
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 8080,
    },
  };
});
