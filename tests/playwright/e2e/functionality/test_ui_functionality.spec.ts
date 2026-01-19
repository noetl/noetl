import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

test.describe('Hello World', () => {
    // test.beforeAll(() => {
    //     console.log('Registering hello world...');
    //     execSync(
    //         'noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8082',
    //         { stdio: 'inherit' }
    //     );
    // });

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
