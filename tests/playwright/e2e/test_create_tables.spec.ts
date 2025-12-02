import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'tests/fixtures/playbooks/save_storage_test/create_tables';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/save_storage_test/create_tables.yaml';

test.describe('Create Tables', () => {

    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_ID}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should execute create_tables playbook', async ({ page }) => {

        await test.step('Navigate to catalog', async () => {
            await page.goto(`${NOETL_BASE_URL}/catalog`);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        const executeBtn = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='Execute'])[1]`);

        await test.step(`Execute ${PLAYBOOK_ID}`, async () => {
            await executeBtn.click();
        });

        await test.step('Wait for execution page', async () => {
            await expect(page).toHaveURL(/\/execution(\/|$)/, { timeout: 30000 });
        });

        await test.step('Wait for loader to disappear', async () => {
            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
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

        let initialRowData: Record<string, string | undefined>;

        await test.step('Read first execution row', async () => {
            const row = page.locator('.ant-table-tbody > tr:first-child');
            const cells = row.locator('td');
            await expect(cells.first()).toHaveText(/.+/);
            const values = await cells.allTextContents();
            initialRowData = Object.fromEntries(headers.map((k, i) => [k, values[i]]));
            console.log('Initial:', initialRowData);
            await expect(initialRowData.Playbook).toBe(PLAYBOOK_ID);
            await expect(initialRowData.Status).toMatch(/STARTED|RUNNING/);
        });

        await test.step('Wait and reload for completion', async () => {
            await page.waitForTimeout(5000);
            await page.reload();
        });

        await test.step('Validate updated execution row', async () => {
            const updatedRow = page.locator('.ant-table-tbody > tr:first-child');
            const updatedCells = updatedRow.locator('td');
            const updatedValues = await updatedCells.allTextContents();
            const updatedRowData = Object.fromEntries(headers.map((k, i) => [k, updatedValues[i]]));
            console.log('Updated:', updatedRowData);
            await expect(page).toHaveTitle('NoETL Dashboard');
            await expect(updatedRowData.Status).toMatch(/Completed|COMPLETED/);
        });

        await test.step('Open execution details (View button)', async () => {
            // Selector uses 'Unknown' placeholder until UI shows correct playbook label
            const viewButton = page.locator("(//*[text()='Unknown']/following::button[normalize-space()='View'])[1]");
            await viewButton.click();
        });

        await test.step('Validate events table headers', async () => {
            const headerCells = page.locator('thead >> role=columnheader');
            await expect(headerCells).toHaveCount(5);
            await expect(headerCells).toHaveText([
                'Event Type',
                'Node Name',
                'Status',
                'Timestamp',
                'Duration'
            ]);
        });
    });

});
