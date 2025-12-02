import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
const NOETL_BASE_URL = process.env.NOETL_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
const PLAYBOOK_ID = 'save_delegation_test';
const PLAYBOOK_PATH = 'tests/fixtures/playbooks/save_storage_test/save_delegation_test.yaml';

test.describe('Save deligation test', () => {

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

        await test.step('Verify updated row', async () => {
            const updatedRow = page.locator('.ant-table-tbody > tr:first-child');
            const updatedCells = updatedRow.locator('td');
            const updatedValues = await updatedCells.allTextContents();
            const updatedRowData = Object.fromEntries(headers.map((key, i) => [key, updatedValues[i]]));

            console.log(updatedRowData);
            await expect(page).toHaveTitle('NoETL Dashboard');
            await expect(updatedRowData.Status).toBe('Completed');
        });

        await test.step('Open execution details (View button)', async () => {
            const viewButton = page.locator("(//*[text()='Unknown']/following::button[normalize-space()='View'])[1]");
            await viewButton.click();
        });

    });

});
