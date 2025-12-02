import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'save_simple_test';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/save_storage_test/save_simple_test.yaml';

test.describe('Save Simple Test', () => {

    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_ID}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {

        await test.step('Navigate to catalog', async () => {
            await page.goto(`${NOETL_BASE_URL}/catalog`);
        });

        await test.step('Verify title', async () => {
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        const exampleItem = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='Execute'])[1]`);

        await test.step(`Execute ${PLAYBOOK_ID} playbook`, async () => {
            await exampleItem.click();
        });

        await test.step('Wait for execution page', async () => {
            await expect(page).toHaveURL(/\/execution(\/|$)/, { timeout: 30000 });
        });

        const headers = [
            'Execution ID',
            'Playbook',
            'Status',
            'Progress',
            'Start Time',
            'Duration',
            'Actions'
        ];

        await test.step('Wait and reload', async () => {
            await page.waitForTimeout(5000);
            await page.reload();
        });

        await test.step('Validate table headers (ARIA)', async () => {
            const headerCells = page.locator('thead >> role=columnheader');
            await expect(headerCells).toHaveCount(5);
            await expect(headerCells).toHaveText(['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration']);
        });

        await test.step('Validate events (first 3 columns only)', async () => {
            const rows = page.locator('.ant-table-tbody > tr.ant-table-row');
            await expect(rows).toHaveCount(9, { timeout: 10000 });

            const expected = [
                ['playbook_started', 'tests/fixtures/playbooks/hello_world', 'STARTED'],
                ['workflow_initialized', 'workflow', 'COMPLETED'],
                ['step_started', 'test_step', 'RUNNING'],
                ['action_started', 'test_step', 'RUNNING'],
                ['action_completed', 'test_step', 'COMPLETED'],
                ['step_completed', 'test_step', 'COMPLETED'],
                ['playbook_completed', 'tests/fixtures/playbooks/hello_world', 'COMPLETED'],
                ['workflow_completed', 'workflow', 'COMPLETED'],
                ['step_result', 'test_step', 'COMPLETED'],
            ];

            for (let i = 0; i < expected.length; i++) {
                const cells = rows.nth(i).locator('td');
                const cellTexts = await cells.allTextContents();
                const eventType = cellTexts[0]?.trim();
                const nodeName = cellTexts[1]?.trim();
                const status = cellTexts[2]?.replace(/\s+/g, ' ').trim();

                await expect(eventType).toBe(expected[i][0]);
                await expect(nodeName).toBe(expected[i][1]);
                await expect(status).toContain(expected[i][2]);
                // Skip timestamp and duration
            }
        });



    });

});
