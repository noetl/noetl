import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('HTTP DuckDB to Postgres', () => {

    // Run the registration command before all tests in this suite
    test.beforeAll(() => {
        console.log('Registering http_duckdb_postgres...');
        execSync('noetl register tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml --host localhost --port 8082', { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        await test.step('Navigate to catalog', async () => {
            await page.goto('http://localhost:8082/catalog');
        });

        await test.step('Verify title', async () => {
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Execute http_duckdb_postgres playbook', async () => {
            const exampleItem = page.locator("(//*[text()='http_duckdb_postgres']/following::button[normalize-space()='Execute'])[1]");
            await exampleItem.click();
        });

        await test.step('Wait for execution page', async () => {
            await page.waitForURL('**/execution', { timeout: 60000 });
            await expect(page.url()).toContain('/execution');
        });

        await test.step('Wait for loader', async () => {
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

        await test.step('Read first row', async () => {
            const row = page.locator('.ant-table-tbody > tr:first-child');
            const cells = row.locator('td');
            const values = await cells.allTextContents();
            const rowData = Object.fromEntries(headers.map((key, i) => [key, values[i]]));
            console.log(rowData);
        });

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

        await test.step('Open execution details', async () => {
            const viewButton = page.locator("(//*[text()='Unknown']/following::button[normalize-space()='View'])[1]");
            await viewButton.click();
        });

        await test.step('Validate events table headers (exclude expand column)', async () => {
            const headerCells = page.locator('.ant-table-thead th:not(.ant-table-row-expand-icon-cell)');
            await expect(headerCells).toHaveCount(5);
            await expect(headerCells.nth(0)).toHaveText('Event Type');
            await expect(headerCells.nth(1)).toHaveText('Node Name');
            await expect(headerCells.nth(2)).toHaveText('Status');
            await expect(headerCells.nth(3)).toHaveText('Timestamp');
            await expect(headerCells.nth(4)).toHaveText('Duration');
        });
    });

});
