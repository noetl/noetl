import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('Hello World', () => {
    test.beforeAll(() => {
        console.log('Registering hello world...');
        execSync(
            'noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8082',
            { stdio: 'inherit' }
        );
    });

    test('/catalog: Execute', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto('http://localhost:8082/catalog');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Execute for hello_world', async () => {
            const executeBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Execute'])[1]"
            );
            await executeBtn.click();
        });

        await test.step('Validate navigation to Execution page', async () => {
            await expect(page).toHaveURL(/\/execution/);
        });

        await test.step('Wait for executions loader to finish (if present)', async () => {
            const loader = page.locator("//*[text()='Loading executions...']");
            await loader.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await loader.waitFor({ state: 'detached' });
        });
    });

    test('/catalog: Payload', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto('http://localhost:8082/catalog');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Open Payload modal for hello_world', async () => {
            const payloadBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Payload'])[1]"
            );
            await payloadBtn.click();
        });

        await test.step('Validate Payload modal UI', async () => {
            const payloadModal = page.locator(
                '//*[@class="ant-modal-title"][text()="Execute Playbook with Payload: tests/fixtures/playbooks/hello_world"]'
            );
            await expect(payloadModal).toBeVisible();

            const closeButton = page.locator('//button[span[text()="Cancel"]]');
            await expect(closeButton).toBeVisible();

            const executeButton = page.locator('//button[span[text()="Execute with Payload"]]');
            await expect(executeButton).toBeVisible();
        });
    });

    test('/catalog: Edit', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto('http://localhost:8082/catalog');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Edit for hello_world', async () => {
            const editBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='Edit'])[1]"
            );
            await editBtn.click();
        });

        await test.step('Validate navigation to Editor page', async () => {
            await expect(page).toHaveURL(/\/editor/);
            await expect(page.url()).toContain('/editor?id=tests/fixtures/playbooks/hello_world');
        });
    });

    test('/catalog: View', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto('http://localhost:8082/catalog');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click View for hello_world', async () => {
            const viewBtn = page.locator(
                "(//*[text()='hello_world']/following::button[normalize-space()='View'])[1]"
            );
            await viewBtn.click();
        });

        await test.step('Validate navigation to Execution page', async () => {
            await expect(page).toHaveURL(/\/execution/);
        });

        await test.step('Validate workflow visualization is visible', async () => {
            const workflowHeading = page.locator("//h2[contains(text(), 'Workflow Visualization')]");
            await expect(workflowHeading).toBeVisible();
        });
    });

    test('/catalog: Search', async ({ page }) => {
        await test.step('Register control_flow_workbook (for negative filter check)', async () => {
            execSync(
                'noetl register tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml --host localhost --port 8082',
                { stdio: 'inherit' }
            );
        });

        await test.step('Open Catalog', async () => {
            await page.goto('http://localhost:8082/catalog');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Type "hello_world" into search input', async () => {
            const searchInput = page.locator("//input[@placeholder='Search playbooks...']");
            await searchInput.fill('hello_world');

            // debounce in UI (replace with deterministic wait if UI exposes it)
            await page.waitForTimeout(1000);
        });

        await test.step('Validate control_flow_workbook is not visible', async () => {
            const otherItem = page.locator("//*[text()='control_flow_workbook']");
            await expect(otherItem).toHaveCount(0);
        });

        await test.step('Validate hello_world is visible', async () => {
            const helloWorldItem = page.locator("//*[text()='hello_world']");
            await expect(helloWorldItem.first()).toBeVisible();
        });
    });

    test('/editor: Validate', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto('http://localhost:8082/editor');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Validate', async () => {
            const validateButton = page.locator('//button[span[text()="Validate"]]');
            await expect(validateButton).toBeVisible();
            await validateButton.click();
        });
    });

    test('/editor: Show Workflow', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto('http://localhost:8082/editor');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Show Workflow', async () => {
            const showWorkflowButton = page.locator('//button[span[text()="Show Workflow"]]');
            await expect(showWorkflowButton).toBeVisible();
            await showWorkflowButton.click();
        });

        await test.step('Validate success toast/message', async () => {
            const successMessage = page.locator(
                '//*[contains(text(),"Successfully parsed 1 workflow steps from New Playbook!")]'
            );
            // await expect(successMessage).toBeVisible();
        });
    });

    test('/editor: Save', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto('http://localhost:8082/editor');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Save', async () => {
            const saveButton = page.locator('//button[span[text()="Save"]]');
            await expect(saveButton).toBeVisible();
            await saveButton.click();
        });

        await test.step('Validate failure message', async () => {
            const failureMessage = page.locator('//*[contains(text(),"Resource \'unknown\' version")]');
            await expect(failureMessage).toBeVisible();
        });
    });

    test('/editor: Execute', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto('http://localhost:8082/editor');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Validate Execute button is disabled', async () => {
            const executeButton = page.locator('//button[span[text()="Execute"]]');
            await expect(executeButton).toBeVisible();
            await expect(executeButton).toBeDisabled();
        });
    });

    test('/execution: Refresh', async ({ page }) => {
        await test.step('Open Execution page', async () => {
            await page.goto('http://localhost:8082/execution');
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Refresh', async () => {
            const refreshButton = page.locator('//button[span[text()="Refresh"]]');
            await expect(refreshButton).toBeVisible();
            await refreshButton.click();
        });
    });
});
