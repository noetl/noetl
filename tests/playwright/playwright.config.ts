import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  timeout: 100000,
  use: {
    baseURL: process.env.NOETL_UI_BASE_URL ?? process.env.NOETL_BASE_URL ?? 'http://localhost:30080',
    trace: 'off',
    video: 'off',
    screenshot: 'off',
  },

  fullyParallel: false,
  workers: 1,

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
