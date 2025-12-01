import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'tests/fixtures/playbooks/playbook_composition/playbook_composition';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/playbook_composition/playbook_composition.yaml';

test.describe('Playbook Composition', () => {

    test.beforeAll(() => {
        console.log(`Registering ${PLAYBOOK_ID}...`);
        execSync(`noetl register ${PLAYBOOK_PATH} --host ${NOETL_HOST} --port ${NOETL_PORT}`, { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        await test.step('Navigate to the catalog page', async () => {
            await page.goto(`${NOETL_BASE_URL}/catalog`);
        });

        await test.step('Check that the page title contains "NoETL Dashboard"', async () => {
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        const exampleItem = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='Execute'])[1]`);

        await test.step(`Click Execute for ${PLAYBOOK_ID}`, async () => {
            await exampleItem.click();
        });

        await test.step('Wait until URL contains "/execution"', async () => {
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

        await test.step('Read first row values', async () => {
            const row = page.locator('.ant-table-tbody > tr:first-child');
            const cells = row.locator('td');
            await expect(cells.first()).toHaveText(/.+/);
            const values = await cells.allTextContents();
            const rowData = Object.fromEntries(headers.map((key, i) => [key, values[i]]));
            console.log(rowData);

            await expect(rowData.Playbook).toBe(PLAYBOOK_ID);
            await expect(rowData.Status).toMatch(/STARTED|RUNNING|COMPLETED|FAILED/);
        });

        await test.step('Wait and reload page', async () => {
            await page.waitForTimeout(10000);
            await page.reload();
        });

        await test.step('Validate updated row values', async () => {
            const updatedRow = page.locator('.ant-table-tbody > tr:first-child');
            const updatedCells = updatedRow.locator('td');
            const updatedValues = await updatedCells.allTextContents();
            const updatedRowData = Object.fromEntries(headers.map((key, i) => [key, updatedValues[i]]));
            console.log(updatedRowData);

            await expect(page).toHaveTitle('NoETL Dashboard');
            await expect(updatedRowData.Status).toMatch(/COMPLETED|FAILED/);
        });

        await test.step('Open execution details via View button', async () => {
            const viewButton = page.locator(`(//*[text()='${PLAYBOOK_ID}']/following::button[normalize-space()='View'])[1]`);
            await viewButton.click();
        });

        await test.step('Validate events table headers (ARIA)', async () => {
            const headerCells = page.locator('thead >> role=columnheader');
            await expect(headerCells).toHaveCount(5);
            await expect(headerCells).toHaveText(['Event Type', 'Node Name', 'Status', 'Timestamp', 'Duration']);
        });
    });

});
