import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  timeout: 100000,
  use: {
    trace: 'off',
    video: 'off',
    screenshot: 'off',
  },

  fullyParallel: true,

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});