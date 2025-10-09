import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('HTTP DuckDB to Postgres', () => {

    // Run the registration command before all tests in this suite
    test.beforeAll(() => {
        console.log('Registering http_duckdb_postgres...');
        execSync('noetl register tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml --host localhost --port 8082', { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "http_duckdb_postgres"
        const exampleItem = page.locator("(//*[text()='http_duckdb_postgres']/following::button[normalize-space()='Execute'])[1]");

        // Inside that element, find the child with text "Execute" and click it
        await exampleItem.click();

        // wait until URL contains "/execution"
        await page.waitForURL('**/execution', { timeout: 60000 });

        // now check
        await expect(page.url()).toContain('/execution');

        const loader = page.locator("//*[text()='Loading executions...']");
        await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
        // Wait for the loader to disappear
        await loader.waitFor({ state: 'detached' });

        const headers = [
            'Execution ID',
            'Playbook',
            'Status',
            'Progress',
            'Start Time',
            'Duration',
            'Actions'
        ];

        // Choose the first row of the table
        const row = page.locator('.ant-table-tbody > tr:first-child');
        const cells = row.locator('td');

        // Get all text contents of the cells in the row
        const values = await cells.allTextContents();

        // Map headers to their corresponding values
        const rowData = Object.fromEntries(headers.map((key, i) => [key, values[i]]));

        console.log(rowData);

        // Assertions
        // await expect(rowData.Playbook).toBe('http_duckdb_postgres');
        // await expect(rowData.Status).toBe('STARTED');
        // await expect(rowData.Duration).toBe('8h 0m');

        // Wait a bit for the execution to complete
        await page.waitForTimeout(5000);
        // Refresh the page
        await page.reload();

        // Choose the first row of the table again
        const updatedRow = page.locator('.ant-table-tbody > tr:first-child');
        const updatedCells = updatedRow.locator('td');
        // Get all text contents of the cells in the row
        const updatedValues = await updatedCells.allTextContents();
        // Map headers to their corresponding values
        const updatedRowData = Object.fromEntries(headers.map((key, i) => [key, updatedValues[i]]));

        console.log(updatedRowData);

        // Assert changes
        await expect(page).toHaveTitle('NoETL Dashboard');
        await expect(updatedRowData.Status).toBe('Completed');
        // await expect(updatedRowData.Playbook).toBe('control_flow_workbook');

        // Click the "View" button for the "http_duckdb_postgres" task
        // TODO fix the selector below from "Unknown" to "http_duckdb_postgres"
        const viewButton = await page.locator("(//*[text()='Unknown']/following::button[normalize-space()='View'])[1]");
        await viewButton.click();

    });

});
