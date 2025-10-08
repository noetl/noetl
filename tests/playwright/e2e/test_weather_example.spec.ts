import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('Weather Example', () => {

    // Run the registration command before all tests in this suite
    test.beforeAll(() => {
        console.log('Registering weather example...');
        execSync('noetl register ./examples/weather/weather_example.yaml --host localhost --port 8082', { stdio: 'inherit' });
    });

    test('should open catalog page', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "weather_example"
        const exampleItem = page.locator("(//*[text()='weather_example']/following::button[normalize-space()='Execute'])[1]");

        // Inside that element, find the child with text "Execute" and click it
        await exampleItem.click();

        // wait until URL contains "/execution"
        await page.waitForURL('**/execution', { timeout: 60000 });

        // now check
        await expect(page.url()).toContain('/execution');

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
        await expect(rowData.Playbook).toBe('weather_example');
        await expect(rowData.Status).toBe('Running');
        await expect(rowData.Duration).toBe('8h 0m');

    });

});
