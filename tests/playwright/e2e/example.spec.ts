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
        const exampleItem = page.locator("//*[text()='weather_example']").first();

        // Inside that element, find the child with text "Execute" and click it
        const executeButton = exampleItem.locator("//*[text()='Execute']");
        await executeButton.click();
    });

});
