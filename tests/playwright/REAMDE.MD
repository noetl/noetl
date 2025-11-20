# Playwright Tests

## Install & Setup
```bash
npm install -D @playwright/test
npx playwright install
```

## Run Modes
```bash
npx playwright test --ui            # Mini app (visual runner)
npx playwright test --debug         # Debug (step through)
npx playwright test path/to/test.spec.ts --debug  # Single test
```

## Python / NoETL Local Env
```bash
uv venv
source .venv/bin/activate
pip install -e .
noetl register ./examples/weather/weather_example.yaml --host $NOETL_HOST --port $NOETL_PORT
```

## Tasks
```bash
task kind-delete-cluster
task ba
```

---

## Best Practices (Playwright + NoETL)

### 1. Use Environment Variables (no hardcoded localhost/ports)
Set before running tests:
```bash
export NOETL_HOST=localhost
export NOETL_PORT=8082
export NOETL_BASE_URL="http://${NOETL_HOST}:${NOETL_PORT}"
```
In tests:
```ts
const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
```

### 2. Register Playbooks in beforeAll
```ts
test.beforeAll(() => {
  execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
});
```

### 3. Wrap Logical Actions in test.step
Benefits: clearer reports, easier debugging.
```ts
await test.step('Execute playbook', async () => {
  const btn = page.locator(`(//*[text()='my_playbook']/following::button[normalize-space()='Execute'])[1]`);
  await btn.click();
  await page.waitForURL('**/execution');
});
```

### 4. Avoid Brittle XPath Where Possible
Prefer:
- data-testid attributes in UI
- `page.getByTestId('playbook-execute-xyz')`
- `page.getByRole('button', { name: 'Execute' })`

Add data-testid in UI components to stabilize selectors.

### 5. Poll for Dynamic Completion (not fixed timeouts)
```ts
await expect.poll(async () => {
  await page.reload();
  const statusCell = page.locator('.ant-table-tbody > tr:first-child td').nth(2);
  return await statusCell.textContent();
}, { timeout: 30000, intervals: [1500] }).toBe('COMPLETED');
```
