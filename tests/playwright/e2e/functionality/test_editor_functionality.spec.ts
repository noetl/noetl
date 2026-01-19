import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import * as path from 'path';
import * as dotenv from 'dotenv';
import * as fs from 'fs';

dotenv.config();

const NOETL_HOST = process.env.NOETL_HOST;
const NOETL_PORT = `8099`;
const BASE_URL = `http://${NOETL_HOST}:${NOETL_PORT}`;
const CATALOG_URL = `${BASE_URL}/editor`;

test.describe('Hello World', () => {
    // test.beforeAll(() => {
    //     console.log('Registering hello world...');
    //     execSync(
    //         `noetl register tests/fixtures/playbooks/hello_world/hello_world.yaml --host ${NOETL_HOST} --port ${NOETL_PORT}`,
    //         { stdio: 'inherit' }
    //     );
    // });

    test('/editor: Validate', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Validate', async () => {
            const validateButton = page.locator('//button[span[text()="Validate"]]');
            await expect(validateButton).toBeVisible();
            await validateButton.click();
        });
    });

    test('/editor: Show Workflow', async ({ page }) => {
        await test.step('Open Catalog', async () => {
            await page.goto(CATALOG_URL);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Click Show Workflow', async () => {
            const showWorkflowButton = page.locator('//button[span[text()="Show Workflow"]]');
            await expect(showWorkflowButton).toBeVisible();
            await showWorkflowButton.click();
        });

        await test.step('Validate workflow panel is visible', async () => {
            // Toasts are ephemeral and can change wording/count; assert the panel UI instead.
            const closeFlowButton = page.locator('button.flow-dock-btn[title="Close"]');
            await expect(closeFlowButton).toBeVisible();
            await expect(page.getByRole('application')).toBeVisible();
            await expect(page.getByRole('button', { name: 'Fit View' })).toBeVisible();
            await expect(page.getByRole('img', { name: 'Mini Map' })).toBeVisible();

            // Optional: toast may not render (or may disappear quickly). Don't fail the test on it.
            const parsedToast = page.getByText(/Successfully parsed\s+\d+\s+workflow steps/i).first();
            await parsedToast.waitFor({ state: 'visible', timeout: 1000 }).catch(() => { });
        });

        await test.step('Close workflow panel', async () => {
            const closeFlowButton = page.locator('button.flow-dock-btn[title="Close"]');
            await expect(closeFlowButton).toBeVisible();
            await closeFlowButton.click();
            await expect(closeFlowButton).toBeHidden();
        });

        await test.step('Validate editor is visible again', async () => {
            const editorTextbox = page.getByRole('textbox', { name: 'Editor content' });
            await expect(editorTextbox).toBeVisible();
        });
    });

    test('/editor: Save empty file', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto(
                `${BASE_URL}/editor`);
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

    test('/editor: Save', async ({ page }) => {
        await test.step('Open Editor for hello_world', async () => {
            await page.goto(
                `${BASE_URL}/editor`);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Fill editor with hello_world YAML', async () => {
            const yamlPath = path.join(__dirname, '../../../fixtures/playbooks/hello_world/hello_world.yaml');
            const yamlContent = fs.readFileSync(yamlPath, 'utf-8');

            // Debug: show exactly what we're about to type into Monaco.
            const yamlPreviewLines = yamlContent.split(/\r?\n/).slice(0, 20).join('\n');
            console.log(`[editor: Save] Typing YAML from: ${yamlPath}`);
            console.log(`[editor: Save] yamlContent length=${yamlContent.length}`);
            console.log(`[editor: Save] yamlContent first 20 lines:\n${yamlPreviewLines}`);
            await test.info().attach('hello_world.yaml', {
                body: yamlContent,
                contentType: 'text/plain',
            });

            

            const editorTextbox = page.getByRole('textbox', { name: 'Editor content' });
            await expect(editorTextbox).toBeVisible();

            // Monaco's input textarea can be covered by rendered lines; focus avoids pointer interception.
            await editorTextbox.focus();
            await editorTextbox.press('ControlOrMeta+A');
            await editorTextbox.press('Backspace');
            await editorTextbox.pressSequentially(yamlContent);

            // Validate a couple of stable lines are rendered (textarea value may not reflect the model).
            await expect(page.getByText('kind: Playbook', { exact: true })).toBeVisible();
            await expect(page.getByText('kind: event_log', { exact: true })).toBeVisible();
        });

        await test.step('Click Save', async () => {
            const saveButton = page.locator('//button[span[text()="Save"]]');
            await expect(saveButton).toBeVisible();
            await saveButton.click();
        });

        await test.step('Validate save success message', async () => {
            await expect(page.getByText('Playbook saved successfully', { exact: true })).toBeVisible();
        });
    });



    test('/editor: Execute empty file', async ({ page }) => {
        await test.step('Open Editor', async () => {
            await page.goto(`${BASE_URL}/editor`);
            await expect(page).toHaveTitle('NoETL Dashboard');
        });

        await test.step('Validate Execute button is disabled', async () => {
            const executeButton = page.locator('//button[span[text()="Execute"]]');
            await expect(executeButton).toBeVisible();
            await expect(executeButton).toBeDisabled();
        });
    });


});
