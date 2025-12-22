import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('Hello World', () => {

    // Run the registration command before all tests in this suite
    test.beforeAll(() => {
        console.log('Registering hello world...');
        execSync('noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8082', { stdio: 'inherit' });
    });

    test('/catalog: Execute', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "hello_world"
        const exampleItem = page.locator("(//*[text()='hello_world']/following::button[normalize-space()='Execute'])[1]");

        // Inside that element, find the child with text "Execute" and click it
        await exampleItem.click();

        // wait until URL contains "/execution"
        // await page.waitForURL('**/execution', { timeout: 60000 });

        // now check
        await expect(page).toHaveURL(/\/execution/);
        // await expect(page.url()).toContain('/execution');

        const loader = page.locator("//*[text()='Loading executions...']");
        await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
        // Wait for the loader to disappear
        await loader.waitFor({ state: 'detached' });
    });

    test('/catalog: Payload', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "hello_world"
        const exampleItem = page.locator("(//*[text()='hello_world']/following::button[normalize-space()='Payload'])[1]");

        // Inside that element, find the child with text "Payload" and click it
        await exampleItem.click();

        // Verify locator for payload modal
        const payloadModal = page.locator('//*[@class="ant-modal-title"][text()="Execute Playbook with Payload: tests/fixtures/playbooks/hello_world"]');
        await expect(payloadModal).toBeVisible();

        // Verify button to close the modal
        const closeButton = page.locator('//button[span[text()="Cancel"]]');
        await expect(closeButton).toBeVisible();

        // Verify button to execute the playbook
        const executeButton = page.locator('//button[span[text()="Execute with Payload"]]');
        await expect(executeButton).toBeVisible();
    });

    test('/catalog: Edit', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "hello_world"
        const exampleItem = page.locator("(//*[text()='hello_world']/following::button[normalize-space()='Edit'])[1]");

        // Inside that element, find the child with text "Edit" and click it
        await exampleItem.click();

        // wait until URL contains "/editor"
        await expect(page).toHaveURL(/\/editor/);
        // await page.waitForURL('**/editor', { timeout: 60000 });

        // now check
        await expect(page.url()).toContain('/editor?id=tests/fixtures/playbooks/hello_world');
    });

    test('/catalog: View', async ({ page }) => {
        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "hello_world"
        const exampleItem = page.locator("(//*[text()='hello_world']/following::button[normalize-space()='View'])[1]");

        // Inside that element, find the child with text "View" and click it
        await exampleItem.click();

        // wait until URL contains "/execution"
        await expect(page).toHaveURL(/\/execution/);
        // await page.waitForURL('**/execution', { timeout: 60000 });

        // now check
        const workflow_element = page.locator("//h2[contains(text(), 'Workflow Visualization')]");
        await expect(workflow_element).toBeVisible();
        // await expect(page.url()).toContain('/execution?playbook=tests%2Ffixtures%2Fplaybooks%2Fhello_world&view=workflow');
    });

    test('/catalog: Search', async ({ page }) => {
        // Register the playbook control_flow_workbook.yaml to test filtering
        execSync('noetl register tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml --host localhost --port 8082', { stdio: 'inherit' });

        // Navigate to the catalog page
        await page.goto('http://localhost:8082/catalog');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Locate the first element that contains the text "hello_world"
        const exampleItem = page.locator("//input[@placeholder='Search playbooks...']");

        // Fill the search input
        await exampleItem.fill('hello_world');

        // Wait a bit for the filtering to take effect
        await page.waitForTimeout(1000);

        // Don't find any other playbook items (for example, "control_flow_workbook")
        const otherItem = page.locator("//*[text()='control_flow_workbook']");
        await expect(otherItem).toHaveCount(0);

        // Verify that "hello_world" item is still present
        const helloWorldItem = page.locator("//*[text()='hello_world']");
        await expect(helloWorldItem).toHaveCount(1);
    });

    test('/editor: Validate', async ({ page }) => {
        // Navigate to the editor page
        await page.goto('http://localhost:8082/editor');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Verify Validate button is present
        const validateButton = page.locator('//button[span[text()="Validate"]]');
        await expect(validateButton).toBeVisible();
        await validateButton.click();

        // Verify success message
        // const successMessage = page.locator('//*[contains(text(),"Playbook is valid!")]');
        // await expect(successMessage).toBeVisible();
    });

    test('/editor: Show Workflow', async ({ page }) => {
        // Navigate to the editor page
        await page.goto('http://localhost:8082/editor');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Verify Show Workflow button is present
        const showWorkflowButton = page.locator('//button[span[text()="Show Workflow"]]');
        await expect(showWorkflowButton).toBeVisible();
        await showWorkflowButton.click();

        // Verify success message
        const successMessage = page.locator('//*[contains(text(),"Successfully parsed 1 workflow steps from New Playbook!")]');
        await expect(successMessage).toBeVisible();
    });

    test('/editor: Save', async ({ page }) => {
        // Navigate to the editor page
        await page.goto('http://localhost:8082/editor');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Verify Save button is present
        const saveButton = page.locator('//button[span[text()="Save"]]');
        await expect(saveButton).toBeVisible();
        await saveButton.click();

        // Verify failure message (since we didn't modify anything, saving should fail)
        const failureMessage = page.locator('//*[contains(text(),"Failed to save playbooks")]');
        await expect(failureMessage).toBeVisible();
    });

    test('/editor: Execute', async ({ page }) => {
        // Navigate to the editor page
        await page.goto('http://localhost:8082/editor');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Verify Execute button is present, but disabled(since we didn't modify anything)
        const executeButton = page.locator('//button[span[text()="Execute"]]');
        await expect(executeButton).toBeVisible();
        await expect(executeButton).toBeDisabled();
    });

    test('/execution: Refresh', async ({ page }) => {
        // Navigate to the execution page
        await page.goto('http://localhost:8082/execution');

        // Check that the page title contains "NoETL Dashboard"
        await expect(page).toHaveTitle('NoETL Dashboard');

        // Verify Refresh button is present
        const refreshButton = page.locator('//button[span[text()="Refresh"]]');
        await expect(refreshButton).toBeVisible();
        await refreshButton.click();
    });
});
